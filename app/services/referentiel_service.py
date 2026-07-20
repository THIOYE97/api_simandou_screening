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

# ===========================================================================
# Listes GAFI / FATF — INSTANTANÉ à réconcilier périodiquement.
#
# Source officielle : https://www.fatf-gafi.org (les listes sont révisées à
# chaque plénière, ~3 fois par an). Cet instantané reflète l'état connu début
# 2025. La Conformité DOIT le valider contre la dernière publication FATF ; les
# indicateurs pays (haut risque / non coopératif / poids) restent éditables à
# chaud via PATCH /referentiel/countries.
# ===========================================================================

# GAFI — « Juridictions à haut risque faisant l'objet d'un appel à l'action »
# (liste noire). Stable depuis plusieurs années.
_GAFI_BLACKLIST = [
    ("IR", "Iran"),
    ("KP", "Corée du Nord"),
    ("MM", "Myanmar"),
]

# GAFI — « Juridictions sous surveillance renforcée » (liste grise).
_GAFI_GREYLIST = [
    ("DZ", "Algérie"), ("AO", "Angola"), ("BG", "Bulgarie"),
    ("BF", "Burkina Faso"), ("CM", "Cameroun"), ("CI", "Côte d'Ivoire"),
    ("HR", "Croatie"), ("CD", "Rép. dém. du Congo"), ("HT", "Haïti"),
    ("KE", "Kenya"), ("LA", "Laos"), ("LB", "Liban"),
    ("ML", "Mali"), ("MC", "Monaco"), ("MZ", "Mozambique"),
    ("NA", "Namibie"), ("NP", "Népal"), ("NG", "Nigéria"),
    ("ZA", "Afrique du Sud"), ("SS", "Soudan du Sud"), ("SY", "Syrie"),
    ("TZ", "Tanzanie"), ("VE", "Venezuela"), ("VN", "Viêt Nam"),
    ("YE", "Yémen"),
]

# Référentiel ISO 3166-1 complet (source : paquet iso-codes, noms français).
# Chargé avec un poids nul : ces pays n'ajoutent aucun risque tant que la
# Conformité ne leur en attribue pas un via PATCH /referentiel/countries.
_ALL_COUNTRIES = [
    ("AD", "Andorre"), ("AE", "Émirats arabes unis"), ("AF", "Afghanistan"),
    ("AG", "Antigua-et-Barbuda"), ("AI", "Anguilla"), ("AL", "Albanie"), ("AM", "Arménie"),
    ("AO", "Angola"), ("AQ", "Antarctique"), ("AR", "Argentine"), ("AS", "Samoa américaines"),
    ("AT", "Autriche"), ("AU", "Australie"), ("AW", "Aruba"), ("AX", "Åland, Îles"),
    ("AZ", "Azerbaïdjan"), ("BA", "Bosnie-Herzégovine"), ("BB", "Barbade"),
    ("BD", "Bangladesh"), ("BE", "Belgique"), ("BF", "Burkina Faso"), ("BG", "Bulgarie"),
    ("BH", "Bahreïn"), ("BI", "Burundi"), ("BJ", "Bénin"), ("BL", "Saint-Barthélemy"),
    ("BM", "Bermudes"), ("BN", "Brunéi Darussalam"), ("BO", "Bolivie, état plurinational de"),
    ("BQ", "Bonaire, Saint-Eustache et Saba"), ("BR", "Brésil"), ("BS", "Bahamas"),
    ("BT", "Bhoutan"), ("BV", "Île Bouvet"), ("BW", "Botswana"), ("BY", "Bélarus"),
    ("BZ", "Belize"), ("CA", "Canada"), ("CC", "Cocos (Keeling), Îles"),
    ("CD", "République démocratique du Congo"), ("CF", "République centrafricaine"),
    ("CG", "République du Congo"), ("CH", "Suisse"), ("CI", "Côte d'Ivoire"),
    ("CK", "Îles Cook"), ("CL", "Chili"), ("CM", "Cameroun"), ("CN", "Chine"),
    ("CO", "Colombie"), ("CR", "Costa Rica"), ("CU", "Cuba"), ("CV", "Cap-Vert"),
    ("CW", "Curaçao"), ("CX", "Christmas, Île"), ("CY", "Chypre"), ("CZ", "Tchéquie"),
    ("DE", "Allemagne"), ("DJ", "Djibouti"), ("DK", "Danemark"), ("DM", "Dominique"),
    ("DO", "République dominicaine"), ("DZ", "Algérie"), ("EC", "Équateur"), ("EE", "Estonie"),
    ("EG", "Égypte"), ("EH", "Sahara occidental"), ("ER", "Érythrée"), ("ES", "Espagne"),
    ("ET", "Éthiopie"), ("FI", "Finlande"), ("FJ", "Fidji"),
    ("FK", "Malouines, Îles (Falkland)"), ("FM", "Micronésie, États fédérés de"),
    ("FO", "Îles Féroé"), ("FR", "France"), ("GA", "Gabon"), ("GB", "Royaume-Uni"),
    ("GD", "Grenade"), ("GE", "Géorgie"), ("GF", "Guyane française"), ("GG", "Guernesey"),
    ("GH", "Ghana"), ("GI", "Gibraltar"), ("GL", "Groënland"), ("GM", "Gambie"),
    ("GN", "Guinée"), ("GP", "Guadeloupe"), ("GQ", "Guinée Équatoriale"), ("GR", "Grèce"),
    ("GS", "Géorgie du Sud et les îles Sandwich du Sud"), ("GT", "Guatemala"), ("GU", "Guam"),
    ("GW", "Guinée-Bissau"), ("GY", "Guyana"), ("HK", "Hong Kong"),
    ("HM", "Îles Heard-et-MacDonald"), ("HN", "Honduras"), ("HR", "Croatie"), ("HT", "Haïti"),
    ("HU", "Hongrie"), ("ID", "Indonésie"), ("IE", "Irlande"), ("IL", "Israël"),
    ("IM", "Île de Man"), ("IN", "Inde"), ("IO", "Territoire britannique de l'océan Indien"),
    ("IQ", "Irak"), ("IR", "Iran, République islamique d'"), ("IS", "Islande"),
    ("IT", "Italie"), ("JE", "Jersey"), ("JM", "Jamaïque"), ("JO", "Jordanie"),
    ("JP", "Japon"), ("KE", "Kenya"), ("KG", "Kirghizistan"), ("KH", "Cambodge"),
    ("KI", "Kiribati"), ("KM", "Comores"), ("KN", "Saint-Christophe-et-Niévès"),
    ("KP", "Corée, République populaire démocratique de"), ("KR", "Corée, République de"),
    ("KW", "Koweït"), ("KY", "Îles Caïmans"), ("KZ", "Kazakhstan"),
    ("LA", "Lao, République démocratique populaire"), ("LB", "Liban"), ("LC", "Sainte-Lucie"),
    ("LI", "Liechtenstein"), ("LK", "Sri Lanka"), ("LR", "Libéria"), ("LS", "Lesotho"),
    ("LT", "Lituanie"), ("LU", "Luxembourg"), ("LV", "Lettonie"), ("LY", "Libye"),
    ("MA", "Maroc"), ("MC", "Monaco"), ("MD", "Moldova, République de"), ("ME", "Monténégro"),
    ("MF", "Saint-Martin (partie française)"), ("MG", "Madagascar"), ("MH", "Îles Marshall"),
    ("MK", "Macédoine du Nord"), ("ML", "Mali"), ("MM", "Birmanie"), ("MN", "Mongolie"),
    ("MO", "Macau"), ("MP", "Îles Mariannes du Nord"), ("MQ", "Martinique"),
    ("MR", "Mauritanie"), ("MS", "Montserrat"), ("MT", "Malte"), ("MU", "Maurice"),
    ("MV", "Maldives"), ("MW", "Malawi"), ("MX", "Mexique"), ("MY", "Malaisie"),
    ("MZ", "Mozambique"), ("NA", "Namibie"), ("NC", "Nouvelle-Calédonie"), ("NE", "Niger"),
    ("NF", "Île Norfolk"), ("NG", "Nigeria"), ("NI", "Nicaragua"), ("NL", "Pays-Bas"),
    ("NO", "Norvège"), ("NP", "Népal"), ("NR", "Nauru"), ("NU", "Nioue"),
    ("NZ", "Nouvelle-Zélande"), ("OM", "Oman"), ("PA", "Panama"), ("PE", "Pérou"),
    ("PF", "Polynésie française"), ("PG", "Papouasie-Nouvelle-Guinée"), ("PH", "Philippines"),
    ("PK", "Pakistan"), ("PL", "Pologne"), ("PM", "Saint-Pierre-et-Miquelon"),
    ("PN", "Îles Pitcairn"), ("PR", "Porto Rico"), ("PS", "Palestine, État de"),
    ("PT", "Portugal"), ("PW", "Palaos"), ("PY", "Paraguay"), ("QA", "Qatar"),
    ("RE", "Réunion, Île de la"), ("RO", "Roumanie"), ("RS", "Serbie"),
    ("RU", "Russie, Fédération de"), ("RW", "Rwanda"), ("SA", "Arabie saoudite"),
    ("SB", "Salomon, Îles"), ("SC", "Seychelles"), ("SD", "Soudan"), ("SE", "Suède"),
    ("SG", "Singapour"), ("SH", "Sainte-Hélène, Ascension et Tristan da Cunha"),
    ("SI", "Slovénie"), ("SJ", "Svalbard et île Jan Mayen"), ("SK", "Slovaquie"),
    ("SL", "Sierra Leone"), ("SM", "Saint-Marin"), ("SN", "Sénégal"), ("SO", "Somalie"),
    ("SR", "Surinam"), ("SS", "Soudan du Sud"), ("ST", "Sao Tomé-et-Principe"),
    ("SV", "Salvador"), ("SX", "Saint-Martin (partie néerlandaise)"),
    ("SY", "Syrienne, République arabe"), ("SZ", "Eswatini"),
    ("TC", "Îles Turques-et-Caïques"), ("TD", "Tchad"), ("TF", "Terres australes françaises"),
    ("TG", "Togo"), ("TH", "Thaïlande"), ("TJ", "Tadjikistan"), ("TK", "Tokelau"),
    ("TL", "Timor oriental"), ("TM", "Turkménistan"), ("TN", "Tunisie"), ("TO", "Tonga"),
    ("TR", "Turquie"), ("TT", "Trinité-et-Tobago"), ("TV", "Tuvalu"),
    ("TW", "Taïwan, province de Chine"), ("TZ", "Tanzanie, République unie de"),
    ("UA", "Ukraine"), ("UG", "Ouganda"), ("UM", "Îles mineures éloignées des États-Unis"),
    ("US", "États-Unis"), ("UY", "Uruguay"), ("UZ", "Ouzbékistan"),
    ("VA", "Saint-Siège (état de la cité du Vatican)"),
    ("VC", "Saint-Vincent-et-les-Grenadines"), ("VE", "Vénézuela, république bolivarienne du"),
    ("VG", "Îles Vierges britanniques"), ("VI", "Îles Vierges, États-Unis"),
    ("VN", "Viêt Nam"), ("VU", "Vanuatu"), ("WF", "Wallis et Futuna"), ("WS", "Samoa"),
    ("YE", "Yémen"), ("YT", "Mayotte"), ("ZA", "Afrique du Sud"), ("ZM", "Zambie"),
    ("ZW", "Zimbabwe"),
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
        "code": "UBO_SANCTION_MATCH",
        "name": "Bénéficiaire effectif sous sanction",
        "description": "Un bénéficiaire effectif de la personne morale est rapproché d'une liste de sanction.",
        "category": ScenarioCategory.SANCTIONS,
        "severity": Severity.CRITICAL,
        "criteria": {"field": "ubo_match_score", "op": ">=", "value": 65},
        "risk_weight": 90,
    },
    {
        "code": "UBO_PEP",
        "name": "Bénéficiaire effectif politiquement exposé",
        "description": "Un bénéficiaire effectif de la personne morale est une PPE.",
        "category": ScenarioCategory.PEP,
        "severity": Severity.HIGH,
        "criteria": {"field": "ubo_is_pep", "op": "==", "value": True},
        "risk_weight": 45,
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

    # Complète avec tous les autres pays ISO (poids nul, éditables).
    seen = set(existing_iso) | {i for i, _ in _GAFI_BLACKLIST} | {i for i, _ in _GAFI_GREYLIST}
    for iso, name in _ALL_COUNTRIES:
        if iso not in seen:
            db.add(Country(iso_code=iso, name=name, is_high_risk=False,
                           is_non_cooperative=False, risk_weight=0))
            seen.add(iso)
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
