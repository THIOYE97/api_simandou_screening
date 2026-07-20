"""
Module 2 — Contrôle Accès et Sécurité : catalogue des permissions (habilitations)
et rôles par défaut.

Les habilitations sont PARAMÉTRABLES (TDR : « habilitations personnalisables
conformément aux rôles définis dans la politique interne LBC/FT »). Le catalogue
ci-dessous est la référence ; les rôles réels (rôle → permissions) sont stockés
en base (`rbac_roles`) et modifiables via l'API.
"""
from __future__ import annotations

# Wildcard = toutes les permissions
ALL = "*"

# Catalogue des permissions, groupées par module LBC/FT.
PERMISSIONS: dict[str, str] = {
    # M1 Référentiel
    "referentiel:read": "Consulter le référentiel (pays, secteurs, scénarios)",
    "referentiel:write": "Modifier le référentiel et les scénarios paramétrables",
    # M3 Listes
    "lists:read": "Consulter les listes de sanction / nationales",
    "lists:manage": "Gérer les listes nationales / propres BCRG",
    # M4 Identification / screening
    "screening:run": "Lancer un screening d'identification",
    "screening:read": "Consulter les résultats de screening",
    # M5 KYT
    "kyt:ingest": "Injecter / analyser des transactions",
    "kyt:read": "Consulter les transactions",
    "sar:read": "Consulter les déclarations de soupçon",
    "sar:manage": "Créer / traiter les déclarations de soupçon",
    # M6 Alerte
    "ubo:read": "Consulter les bénéficiaires effectifs",
    "ubo:write": "Déclarer et filtrer les bénéficiaires effectifs",
    "alerts:read": "Consulter les alertes",
    "alerts:manage": "Traiter, affecter, clôturer les alertes + règles",
    # M7 Scoring
    "scoring:evaluate": "Évaluer le risque d'un sujet",
    "scoring:read": "Consulter les évaluations de risque",
    # M8 Reportings
    "reports:read": "Consulter et éditer les rapports",
    # Transverse / administration
    "audit:read": "Consulter la piste d'audit",
    "users:manage": "Gérer les utilisateurs",
    "roles:manage": "Gérer les rôles et habilitations",
}

# Rôles par défaut (conformes à une politique LBC/FT type). Modifiables en base.
DEFAULT_ROLES: dict[str, dict] = {
    "OWNER": {
        "name": "Propriétaire",
        "description": "Accès total (super-utilisateur métier).",
        "permissions": [ALL],
    },
    "ADMIN": {
        "name": "Administrateur",
        "description": "Administration de la plateforme et des habilitations.",
        "permissions": [ALL],
    },
    "COMPLIANCE_OFFICER": {
        "name": "Responsable Conformité",
        "description": "Cellule de Conformité : alertes, soupçons, reporting.",
        "permissions": [
            "referentiel:read", "screening:read", "kyt:read", "ubo:read", "ubo:write",
            "alerts:read", "alerts:manage", "sar:read", "sar:manage",
            "scoring:read", "reports:read", "audit:read",
        ],
    },
    "ANALYST": {
        "name": "Analyste",
        "description": "Analyse opérationnelle : screening, KYT, alertes.",
        "permissions": [
            "referentiel:read", "screening:run", "screening:read",
            "kyt:ingest", "kyt:read", "scoring:evaluate", "scoring:read", "ubo:read", "ubo:write",
            "alerts:read", "sar:read", "reports:read",
        ],
    },
    "REFERENTIEL_ADMIN": {
        "name": "Administrateur Référentiel",
        "description": "Paramétrage du référentiel et des scénarios / règles.",
        "permissions": [
            "referentiel:read", "referentiel:write",
            "lists:read", "lists:manage", "alerts:read", "alerts:manage",
        ],
    },
    "AUDITOR": {
        "name": "Auditeur",
        "description": "Consultation en lecture seule + piste d'audit.",
        "permissions": [
            "referentiel:read", "screening:read", "kyt:read", "ubo:read", "ubo:write", "alerts:read",
            "sar:read", "scoring:read", "reports:read", "audit:read", "lists:read",
        ],
    },
    "VIEWER": {
        "name": "Consultation",
        "description": "Lecture seule limitée.",
        "permissions": ["screening:read", "alerts:read", "reports:read"],
    },
}


def role_has_permission(permissions: list[str], required: str) -> bool:
    return ALL in permissions or required in permissions
