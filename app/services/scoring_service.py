"""
Service métier — Module 7 Scoring.

Moteur d'évaluation paramétrable :
1. enrichit le contexte (résout les pays à risque, la catégorie client…) ;
2. évalue chaque scénario ACTIF du Référentiel (M1) contre le contexte ;
3. somme les pondérations des scénarios déclenchés (+ base catégorie client) ;
4. classe le risque selon des seuils paramétrables ;
5. persiste un RiskAssessment (historisation).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.referentiel import ClientCategory, Country, RiskScenario
from app.models.scoring import RiskAssessment, RiskClass, SubjectType

# Seuils de classification (paramétrables) : borne haute exclusive.
RISK_THRESHOLDS = [
    (25, RiskClass.LOW),
    (50, RiskClass.MEDIUM),
    (100, RiskClass.HIGH),
]  # au-delà de 100 → CRITICAL


# --- Évaluation d'un critère -------------------------------------------------

def _apply_op(actual: Any, op: str, expected: Any) -> bool:
    try:
        if op == "==":
            return actual == expected
        if op == "!=":
            return actual != expected
        if op == ">":
            return actual is not None and actual > expected
        if op == ">=":
            return actual is not None and actual >= expected
        if op == "<":
            return actual is not None and actual < expected
        if op == "<=":
            return actual is not None and actual <= expected
        if op == "in":
            return actual in (expected or [])
        if op == "not_in":
            return actual not in (expected or [])
    except TypeError:
        return False
    return False


def _match(criteria: dict, ctx: dict) -> bool:
    """Un critère = {field, op, value}. Champ absent du contexte → non déclenché."""
    field = criteria.get("field")
    op = criteria.get("op", "==")
    expected = criteria.get("value")
    if field is None or field not in ctx:
        return False
    return _apply_op(ctx.get(field), op, expected)


# --- Résolution des pays -----------------------------------------------------
# Le référentiel stocke des codes ISO à 2 lettres. Les agents saisissent
# pourtant souvent l'ISO à 3 lettres (SEN, CIV) ou une abréviation d'usage
# (RCI, RDC), voire un nom sans accent. Sans tolérance, le pays n'est pas
# reconnu et le risque géographique est silencieusement ignoré.

_ALPHA3_TO_ALPHA2 = {
    "AND": "AD", "ARE": "AE", "AFG": "AF", "ATG": "AG", "AIA": "AI", "ALB": "AL", "ARM": "AM",
    "AGO": "AO", "ATA": "AQ", "ARG": "AR", "ASM": "AS", "AUT": "AT", "AUS": "AU", "ABW": "AW",
    "ALA": "AX", "AZE": "AZ", "BIH": "BA", "BRB": "BB", "BGD": "BD", "BEL": "BE", "BFA": "BF",
    "BGR": "BG", "BHR": "BH", "BDI": "BI", "BEN": "BJ", "BLM": "BL", "BMU": "BM", "BRN": "BN",
    "BOL": "BO", "BES": "BQ", "BRA": "BR", "BHS": "BS", "BTN": "BT", "BVT": "BV", "BWA": "BW",
    "BLR": "BY", "BLZ": "BZ", "CAN": "CA", "CCK": "CC", "COD": "CD", "CAF": "CF", "COG": "CG",
    "CHE": "CH", "CIV": "CI", "COK": "CK", "CHL": "CL", "CMR": "CM", "CHN": "CN", "COL": "CO",
    "CRI": "CR", "CUB": "CU", "CPV": "CV", "CUW": "CW", "CXR": "CX", "CYP": "CY", "CZE": "CZ",
    "DEU": "DE", "DJI": "DJ", "DNK": "DK", "DMA": "DM", "DOM": "DO", "DZA": "DZ", "ECU": "EC",
    "EST": "EE", "EGY": "EG", "ESH": "EH", "ERI": "ER", "ESP": "ES", "ETH": "ET", "FIN": "FI",
    "FJI": "FJ", "FLK": "FK", "FSM": "FM", "FRO": "FO", "FRA": "FR", "GAB": "GA", "GBR": "GB",
    "GRD": "GD", "GEO": "GE", "GUF": "GF", "GGY": "GG", "GHA": "GH", "GIB": "GI", "GRL": "GL",
    "GMB": "GM", "GIN": "GN", "GLP": "GP", "GNQ": "GQ", "GRC": "GR", "SGS": "GS", "GTM": "GT",
    "GUM": "GU", "GNB": "GW", "GUY": "GY", "HKG": "HK", "HMD": "HM", "HND": "HN", "HRV": "HR",
    "HTI": "HT", "HUN": "HU", "IDN": "ID", "IRL": "IE", "ISR": "IL", "IMN": "IM", "IND": "IN",
    "IOT": "IO", "IRQ": "IQ", "IRN": "IR", "ISL": "IS", "ITA": "IT", "JEY": "JE", "JAM": "JM",
    "JOR": "JO", "JPN": "JP", "KEN": "KE", "KGZ": "KG", "KHM": "KH", "KIR": "KI", "COM": "KM",
    "KNA": "KN", "PRK": "KP", "KOR": "KR", "KWT": "KW", "CYM": "KY", "KAZ": "KZ", "LAO": "LA",
    "LBN": "LB", "LCA": "LC", "LIE": "LI", "LKA": "LK", "LBR": "LR", "LSO": "LS", "LTU": "LT",
    "LUX": "LU", "LVA": "LV", "LBY": "LY", "MAR": "MA", "MCO": "MC", "MDA": "MD", "MNE": "ME",
    "MAF": "MF", "MDG": "MG", "MHL": "MH", "MKD": "MK", "MLI": "ML", "MMR": "MM", "MNG": "MN",
    "MAC": "MO", "MNP": "MP", "MTQ": "MQ", "MRT": "MR", "MSR": "MS", "MLT": "MT", "MUS": "MU",
    "MDV": "MV", "MWI": "MW", "MEX": "MX", "MYS": "MY", "MOZ": "MZ", "NAM": "NA", "NCL": "NC",
    "NER": "NE", "NFK": "NF", "NGA": "NG", "NIC": "NI", "NLD": "NL", "NOR": "NO", "NPL": "NP",
    "NRU": "NR", "NIU": "NU", "NZL": "NZ", "OMN": "OM", "PAN": "PA", "PER": "PE", "PYF": "PF",
    "PNG": "PG", "PHL": "PH", "PAK": "PK", "POL": "PL", "SPM": "PM", "PCN": "PN", "PRI": "PR",
    "PSE": "PS", "PRT": "PT", "PLW": "PW", "PRY": "PY", "QAT": "QA", "REU": "RE", "ROU": "RO",
    "SRB": "RS", "RUS": "RU", "RWA": "RW", "SAU": "SA", "SLB": "SB", "SYC": "SC", "SDN": "SD",
    "SWE": "SE", "SGP": "SG", "SHN": "SH", "SVN": "SI", "SJM": "SJ", "SVK": "SK", "SLE": "SL",
    "SMR": "SM", "SEN": "SN", "SOM": "SO", "SUR": "SR", "SSD": "SS", "STP": "ST", "SLV": "SV",
    "SXM": "SX", "SYR": "SY", "SWZ": "SZ", "TCA": "TC", "TCD": "TD", "ATF": "TF", "TGO": "TG",
    "THA": "TH", "TJK": "TJ", "TKL": "TK", "TLS": "TL", "TKM": "TM", "TUN": "TN", "TON": "TO",
    "TUR": "TR", "TTO": "TT", "TUV": "TV", "TWN": "TW", "TZA": "TZ", "UKR": "UA", "UGA": "UG",
    "UMI": "UM", "USA": "US", "URY": "UY", "UZB": "UZ", "VAT": "VA", "VCT": "VC", "VEN": "VE",
    "VGB": "VG", "VIR": "VI", "VNM": "VN", "VUT": "VU", "WLF": "WF", "WSM": "WS", "YEM": "YE",
    "MYT": "YT", "ZAF": "ZA", "ZMB": "ZM", "ZWE": "ZW",
}

_COUNTRY_ALIASES = {
    "RCI": "CI", "COTE D IVOIRE": "CI", "COTE DIVOIRE": "CI", "IVORY COAST": "CI",
    "RDC": "CD", "DRC": "CD", "CONGO KINSHASA": "CD", "CONGO RDC": "CD",
    "GUINEE": "GN", "GUINEE CONAKRY": "GN", "GUINEA": "GN",
    "ETATS UNIS": "US", "UK": "GB", "ANGLETERRE": "GB", "ROYAUME UNI": "GB",
    "EAU": "AE", "UAE": "AE", "EMIRATS ARABES UNIS": "AE",
    "AFRIQUE DU SUD": "ZA", "SOUTH AFRICA": "ZA",
    "COREE DU NORD": "KP", "NORTH KOREA": "KP", "BIRMANIE": "MM",
}


def _norm_key(value: Any) -> str:
    """Majuscules, sans accents ni ponctuation (« Côte d'Ivoire » → « COTE D IVOIRE »)."""
    txt = unicodedata.normalize("NFD", str(value or ""))
    txt = "".join(c for c in txt if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9]+", " ", txt)).strip().upper()


def resolve_country(db: Session, raw: Any) -> Optional[Country]:
    """Résout un pays depuis un code ISO2/ISO3, un alias d'usage ou un nom."""
    key = _norm_key(raw)
    if not key:
        return None

    code = _COUNTRY_ALIASES.get(key) or _ALPHA3_TO_ALPHA2.get(key)
    if not code and len(key) in (2, 3):
        code = key
    if code:
        found = db.execute(
            select(Country).where(func.upper(Country.iso_code) == code)
        ).scalars().first()
        if found:
            return found

    # Repli : comparaison des noms, insensible aux accents et à la ponctuation.
    for country in db.execute(select(Country)).scalars().all():
        if _norm_key(country.name) == key:
            return country
    return None


# --- Enrichissement du contexte ---------------------------------------------

def enrich_context(db: Session, ctx: dict) -> dict:
    """Ajoute des signaux dérivés du Référentiel à partir des données brutes."""
    out = dict(ctx)

    raw = out.get("country")
    if raw:
        country = resolve_country(db, raw)
        if country:
            out.setdefault("country_is_high_risk", country.is_high_risk)
            out.setdefault("country_is_non_cooperative", country.is_non_cooperative)
            out["_country_weight"] = country.risk_weight if country.active else 0

    return out


# --- Classification ----------------------------------------------------------

def classify(total: int) -> RiskClass:
    for upper, cls in RISK_THRESHOLDS:
        if total < upper:
            return cls
    return RiskClass.CRITICAL


# --- Scoring principal -------------------------------------------------------

def score_subject(
    db: Session,
    subject_type: SubjectType,
    context: dict,
    subject_ref: Optional[str] = None,
    subject_label: Optional[str] = None,
    created_by: Optional[UUID] = None,
    tenant_id: Optional[UUID] = None,
    persist: bool = True,
) -> RiskAssessment:
    ctx = enrich_context(db, context)

    # base : pondération de la catégorie de client
    base = 0
    cat_code = ctx.get("client_category")
    if cat_code:
        cat = db.execute(
            select(ClientCategory).where(ClientCategory.code == cat_code)
        ).scalars().first()
        if cat:
            base = cat.base_risk_weight

    scenarios = db.execute(
        select(RiskScenario).where(RiskScenario.active.is_(True))
    ).scalars().all()

    triggered: list[dict] = []
    total = base
    for sc in scenarios:
        if _match(sc.criteria or {}, ctx):
            triggered.append({
                "code": sc.code,
                "name": sc.name,
                "category": sc.category.value,
                "severity": sc.severity.value,
                "weight": sc.risk_weight,
            })
            total += sc.risk_weight

    total = min(total, 100)  # score plafonné à 100
    assessment = RiskAssessment(
        tenant_id=tenant_id,
        subject_type=subject_type,
        subject_ref=subject_ref,
        subject_label=subject_label,
        total_score=total,
        risk_class=classify(total),
        triggered=triggered,
        context={k: v for k, v in ctx.items() if not k.startswith("_")},
        created_by=created_by,
    )
    if persist:
        db.add(assessment)
        db.commit()
        db.refresh(assessment)
    return assessment


def list_assessments(
    db: Session,
    subject_ref: Optional[str] = None,
    limit: int = 50,
) -> list[RiskAssessment]:
    stmt = select(RiskAssessment).order_by(RiskAssessment.created_at.desc()).limit(limit)
    if subject_ref:
        stmt = select(RiskAssessment).where(
            RiskAssessment.subject_ref == subject_ref
        ).order_by(RiskAssessment.created_at.desc()).limit(limit)
    return list(db.execute(stmt).scalars().all())
