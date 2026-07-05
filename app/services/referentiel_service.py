"""
Service métier — Module 1 Référentiel.

CRUD des nomenclatures + fonction de seed (données de démarrage :
pays GAFI, catégories de clients, secteurs, scénarios de risque par défaut).
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.referentiel import (
    BusinessSector,
    ClientCategory,
    Country,
    Currency,
    RiskScenario,
    ScenarioCategory,
    Severity,
)

# --------------------------------------------------------------------------
# CRUD générique minimal (par type)
# --------------------------------------------------------------------------

def list_countries(db: Session, active_only: bool = False) -> list[Country]:
    stmt = select(Country).order_by(Country.name)
    if active_only:
        stmt = stmt.where(Country.active.is_(True))
    return list(db.execute(stmt).scalars().all())


def create_country(db: Session, data: dict) -> Country:
    obj = Country(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def update_country(db: Session, country_id: UUID, data: dict) -> Optional[Country]:
    obj = db.get(Country, country_id)
    if not obj:
        return None
    for k, v in data.items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


def list_sectors(db: Session) -> list[BusinessSector]:
    return list(db.execute(select(BusinessSector).order_by(BusinessSector.name)).scalars().all())


def create_sector(db: Session, data: dict) -> BusinessSector:
    obj = BusinessSector(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def list_client_categories(db: Session) -> list[ClientCategory]:
    return list(db.execute(select(ClientCategory).order_by(ClientCategory.name)).scalars().all())


def create_client_category(db: Session, data: dict) -> ClientCategory:
    obj = ClientCategory(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def list_scenarios(db: Session, active_only: bool = False) -> list[RiskScenario]:
    stmt = select(RiskScenario).order_by(RiskScenario.code)
    if active_only:
        stmt = stmt.where(RiskScenario.active.is_(True))
    return list(db.execute(stmt).scalars().all())


def create_scenario(db: Session, data: dict) -> RiskScenario:
    obj = RiskScenario(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def update_scenario(db: Session, scenario_id: UUID, data: dict) -> Optional[RiskScenario]:
    obj = db.get(RiskScenario, scenario_id)
    if not obj:
        return None
    for k, v in data.items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


# --------------------------------------------------------------------------
# Données de démarrage (seed idempotent)
# --------------------------------------------------------------------------

# GAFI — liste noire (« appel à l'action ») + non coopératifs
_GAFI_BLACKLIST = [
    ("IR", "Iran"),
    ("KP", "Corée du Nord"),
    ("MM", "Myanmar"),
]

# GAFI — surveillance renforcée (« liste grise ») — extrait représentatif
_GAFI_GREYLIST = [
    ("SY", "Syrie"), ("YE", "Yémen"), ("CD", "Rép. dém. du Congo"),
    ("ML", "Mali"), ("BF", "Burkina Faso"), ("SS", "Soudan du Sud"),
    ("HT", "Haïti"), ("VE", "Venezuela"), ("MZ", "Mozambique"),
]

_DEFAULT_CLIENT_CATEGORIES = [
    ("PARTICULIER", "Particulier", 0),
    ("PME", "Petite/moyenne entreprise", 5),
    ("GRAND_COMPTE", "Grand compte", 10),
    ("PPE", "Personne politiquement exposée", 40),
    ("CORRESPONDANT", "Correspondant bancaire", 25),
    ("ONG", "ONG / association", 15),
]

_DEFAULT_SECTORS = [
    ("BANQUE", "Banque / finance", 10),
    ("IMMO", "Immobilier", 20),
    ("MINES", "Mines / matières premières", 25),
    ("IMPORT_EXPORT", "Import / export", 20),
    ("CRYPTO", "Actifs virtuels / crypto", 35),
    ("JEUX", "Jeux d'argent", 30),
    ("COMMERCE", "Commerce de détail", 5),
]

_DEFAULT_SCENARIOS = [
    {
        "code": "SANCTION_MATCH_STRONG",
        "name": "Correspondance forte liste de sanction",
        "description": "Score de matching élevé contre une liste de sanction.",
        "category": ScenarioCategory.SANCTIONS,
        "severity": Severity.CRITICAL,
        "criteria": {"field": "match_score", "op": ">=", "value": 85},
        "risk_weight": 100,
    },
    {
        "code": "SANCTION_MATCH_PARTIAL",
        "name": "Correspondance partielle liste de sanction",
        "description": "Score de matching modéré nécessitant revue analyste.",
        "category": ScenarioCategory.SANCTIONS,
        "severity": Severity.HIGH,
        "criteria": {"field": "match_score", "op": ">=", "value": 65},
        "risk_weight": 50,
    },
    {
        "code": "PEP_HIT",
        "name": "Personne politiquement exposée",
        "description": "Tiers identifié comme PPE.",
        "category": ScenarioCategory.PEP,
        "severity": Severity.HIGH,
        "criteria": {"field": "is_pep", "op": "==", "value": True},
        "risk_weight": 40,
    },
    {
        "code": "GEO_NON_COOPERATIVE",
        "name": "Pays non coopératif / GAFI",
        "description": "Tiers rattaché à un pays à haut risque GAFI.",
        "category": ScenarioCategory.GEOGRAPHY,
        "severity": Severity.HIGH,
        "criteria": {"field": "country_is_high_risk", "op": "==", "value": True},
        "risk_weight": 30,
    },
    {
        "code": "TXN_LARGE_CASH",
        "name": "Transaction espèces élevée",
        "description": "Opération en espèces au-dessus du seuil réglementaire.",
        "category": ScenarioCategory.TRANSACTION,
        "severity": Severity.MEDIUM,
        "criteria": {"field": "amount", "op": ">", "value": 10000, "currency": "USD", "channel": "CASH"},
        "risk_weight": 20,
    },
    {
        "code": "BEHAVIOR_STRUCTURING",
        "name": "Fractionnement (structuring)",
        "description": "Multiples opérations juste sous le seuil de déclaration.",
        "category": ScenarioCategory.BEHAVIOR,
        "severity": Severity.HIGH,
        "criteria": {"field": "pattern", "op": "==", "value": "structuring", "window_days": 7, "count": 3},
        "risk_weight": 35,
    },
    {
        "code": "ADVERSE_MEDIA_HIT",
        "name": "Presse négative (adverse media)",
        "description": "Tiers rapproché d'un signalement adverse media.",
        "category": ScenarioCategory.ADVERSE_MEDIA,
        "severity": Severity.HIGH,
        "criteria": {"field": "adverse_media_hit", "op": "==", "value": True},
        "risk_weight": 30,
    },
]


# --------------------------------------------------------------------------
# Devises
# --------------------------------------------------------------------------

def list_currencies(db: Session, active_only: bool = False) -> list[Currency]:
    stmt = select(Currency).order_by(Currency.code)
    if active_only:
        stmt = stmt.where(Currency.active.is_(True))
    return list(db.execute(stmt).scalars().all())


def create_currency(db: Session, data: dict) -> Currency:
    data = dict(data)
    if data.get("code"):
        data["code"] = str(data["code"]).upper()
    obj = Currency(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def update_currency(db: Session, currency_id: UUID, data: dict) -> Optional[Currency]:
    obj = db.get(Currency, currency_id)
    if not obj:
        return None
    for k, v in data.items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


# code, name, symbol, region
_CURRENCIES = [
    # Guinée
    ("GNF", "Franc guinéen", "FG", "Guinée"),
    # FCFA
    ("XOF", "Franc CFA (Afrique de l'Ouest)", "CFA", "Afrique de l'Ouest"),
    ("XAF", "Franc CFA (Afrique Centrale)", "FCFA", "Afrique Centrale"),
    # Majeures
    ("USD", "Dollar américain", "$", "International"),
    ("EUR", "Euro", "€", "International"),
    ("GBP", "Livre sterling", "£", "International"),
    ("CHF", "Franc suisse", "CHF", "International"),
    ("CNY", "Yuan chinois", "¥", "International"),
    ("JPY", "Yen japonais", "¥", "International"),
    ("CAD", "Dollar canadien", "$", "International"),
    # Moyen-Orient
    ("AED", "Dirham des Émirats", "د.إ", "Moyen-Orient"),
    ("SAR", "Riyal saoudien", "﷼", "Moyen-Orient"),
    ("QAR", "Riyal qatari", "﷼", "Moyen-Orient"),
    ("KWD", "Dinar koweïtien", "د.ك", "Moyen-Orient"),
    ("BHD", "Dinar bahreïni", ".د.ب", "Moyen-Orient"),
    ("OMR", "Rial omanais", "﷼", "Moyen-Orient"),
    ("JOD", "Dinar jordanien", "د.ا", "Moyen-Orient"),
    ("LBP", "Livre libanaise", "ل.ل", "Moyen-Orient"),
    ("ILS", "Shekel israélien", "₪", "Moyen-Orient"),
    ("IQD", "Dinar irakien", "ع.د", "Moyen-Orient"),
    ("IRR", "Rial iranien", "﷼", "Moyen-Orient"),
    ("TRY", "Livre turque", "₺", "Moyen-Orient"),
    ("YER", "Rial yéménite", "﷼", "Moyen-Orient"),
    # Afrique
    ("NGN", "Naira nigérian", "₦", "Afrique"),
    ("GHS", "Cedi ghanéen", "₵", "Afrique"),
    ("ZAR", "Rand sud-africain", "R", "Afrique"),
    ("KES", "Shilling kényan", "KSh", "Afrique"),
    ("EGP", "Livre égyptienne", "£", "Afrique"),
    ("MAD", "Dirham marocain", "د.م.", "Afrique"),
    ("DZD", "Dinar algérien", "د.ج", "Afrique"),
    ("TND", "Dinar tunisien", "د.ت", "Afrique"),
    ("LYD", "Dinar libyen", "ل.د", "Afrique"),
    ("SDG", "Livre soudanaise", "ج.س.", "Afrique"),
    ("ETB", "Birr éthiopien", "Br", "Afrique"),
    ("UGX", "Shilling ougandais", "USh", "Afrique"),
    ("TZS", "Shilling tanzanien", "TSh", "Afrique"),
    ("RWF", "Franc rwandais", "FRw", "Afrique"),
    ("BIF", "Franc burundais", "FBu", "Afrique"),
    ("MZN", "Metical mozambicain", "MT", "Afrique"),
    ("AOA", "Kwanza angolais", "Kz", "Afrique"),
    ("CDF", "Franc congolais", "FC", "Afrique"),
    ("ZMW", "Kwacha zambien", "ZK", "Afrique"),
    ("BWP", "Pula botswanais", "P", "Afrique"),
    ("MUR", "Roupie mauricienne", "₨", "Afrique"),
    ("GMD", "Dalasi gambien", "D", "Afrique"),
    ("SLE", "Leone sierra-léonais", "Le", "Afrique"),
    ("LRD", "Dollar libérien", "$", "Afrique"),
    ("MRU", "Ouguiya mauritanien", "UM", "Afrique"),
    ("CVE", "Escudo cap-verdien", "$", "Afrique"),
    ("MGA", "Ariary malgache", "Ar", "Afrique"),
    ("MWK", "Kwacha malawite", "MK", "Afrique"),
    ("SOS", "Shilling somalien", "Sh", "Afrique"),
    ("DJF", "Franc djiboutien", "Fdj", "Afrique"),
    ("ERN", "Nakfa érythréen", "Nfk", "Afrique"),
    ("KMF", "Franc comorien", "CF", "Afrique"),
    ("STN", "Dobra santoméen", "Db", "Afrique"),
    ("SCR", "Roupie seychelloise", "₨", "Afrique"),
    ("NAD", "Dollar namibien", "$", "Afrique"),
    ("SZL", "Lilangeni swazi", "L", "Afrique"),
    ("LSL", "Loti lesothan", "L", "Afrique"),
    ("SSP", "Livre sud-soudanaise", "£", "Afrique"),
]


def seed_currencies(db: Session) -> int:
    existing = {c.code for c in list_currencies(db)}
    n = 0
    for code, name, symbol, region in _CURRENCIES:
        if code not in existing:
            db.add(Currency(code=code, name=name, symbol=symbol, region=region))
            n += 1
    db.commit()
    return n


def seed_referentiel(db: Session) -> dict[str, int]:
    """Insère les données par défaut (idempotent : ignore les codes déjà présents)."""
    created = {"countries": 0, "sectors": 0, "client_categories": 0, "scenarios": 0, "currencies": 0}
    created["currencies"] = seed_currencies(db)

    existing_iso = {c.iso_code for c in list_countries(db)}
    for iso, name in _GAFI_BLACKLIST:
        if iso not in existing_iso:
            db.add(Country(iso_code=iso, name=name, is_high_risk=True,
                           is_non_cooperative=True, risk_weight=50))
            created["countries"] += 1
    for iso, name in _GAFI_GREYLIST:
        if iso not in existing_iso:
            db.add(Country(iso_code=iso, name=name, is_high_risk=True,
                           is_non_cooperative=False, risk_weight=25))
            created["countries"] += 1

    existing_sectors = {s.code for s in list_sectors(db)}
    for code, name, w in _DEFAULT_SECTORS:
        if code not in existing_sectors:
            db.add(BusinessSector(code=code, name=name, risk_weight=w))
            created["sectors"] += 1

    existing_cats = {c.code for c in list_client_categories(db)}
    for code, name, w in _DEFAULT_CLIENT_CATEGORIES:
        if code not in existing_cats:
            db.add(ClientCategory(code=code, name=name, base_risk_weight=w))
            created["client_categories"] += 1

    existing_scen = {s.code for s in list_scenarios(db)}
    for s in _DEFAULT_SCENARIOS:
        if s["code"] not in existing_scen:
            db.add(RiskScenario(**s))
            created["scenarios"] += 1

    db.commit()
    return created
