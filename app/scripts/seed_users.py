"""
Seed de production — profils utilisateurs LBC/FT + référentiel de base.

Crée (de façon IDEMPOTENTE) :
  1. les rôles RBAC par défaut ;
  2. le référentiel (pays/GAFI, scénarios, devises, catégories, secteurs) ;
  3. les règles d'alerte par défaut ;
  4. le tenant BCRG ;
  5. deux utilisateurs :
       - CONFORMITÉ  : accès complet (supervision, décisions, paramétrage) ;
       - ANALYSTE    : accès opérationnel (Principal uniquement).

Exécution (Railway / Render / local) :
    python -m app.scripts.seed_users

Mots de passe et emails configurables par variables d'environnement :
    SEED_COMPLIANCE_EMAIL / SEED_COMPLIANCE_PASSWORD
    SEED_ANALYST_EMAIL    / SEED_ANALYST_PASSWORD
"""
from __future__ import annotations

import os
import uuid

from sqlalchemy import text

from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.services import alerting_service, rbac_service, referentiel_service

# Rôles : voir app/core/permissions.py
CONFORMITE_ROLE = "ADMIN"       # « * » : accès complet + décisions + paramétrage
ANALYSTE_ROLE = "ANALYST"       # Principal seul (pas de gestion des alertes)


def _ensure_tenant(bypass_conn) -> str:
    tid = bypass_conn.execute(text("SELECT id::text FROM tenants WHERE slug = 'bcrg' LIMIT 1")).scalar()
    if tid:
        return tid
    tid = str(uuid.uuid4())
    bypass_conn.execute(
        text("INSERT INTO tenants (id, name, slug, status) VALUES (:i, 'BCRG', 'bcrg', 'ACTIVE')"),
        {"i": tid},
    )
    print(f"  + tenant BCRG créé ({tid[:8]}…)")
    return tid


def _ensure_user(bypass_conn, email: str, full_name: str, password: str, tenant_id: str) -> str:
    from app.services.auth_service import hash_password

    uid = bypass_conn.execute(text("SELECT id::text FROM users WHERE email = :e"), {"e": email}).scalar()
    if uid:
        print(f"  = utilisateur déjà présent : {email}")
        return uid
    uid = str(uuid.uuid4())
    bypass_conn.execute(
        text("""
            INSERT INTO users (id, email, full_name, password_hash, is_active, status, tenant_id)
            VALUES (:i, :e, :n, :p, true, 'ACTIVE', :t)
        """),
        {"i": uid, "e": email, "n": full_name, "p": hash_password(password), "t": tenant_id},
    )
    print(f"  + utilisateur créé : {email}")
    return uid


def main() -> None:
    conf_email = os.getenv("SEED_COMPLIANCE_EMAIL", "conformite@bcrg-guinee.org")
    conf_pwd = os.getenv("SEED_COMPLIANCE_PASSWORD", "Conformite@2026")
    ana_email = os.getenv("SEED_ANALYST_EMAIL", "analyste@bcrg-guinee.org")
    ana_pwd = os.getenv("SEED_ANALYST_PASSWORD", "Analyste@2026")

    print("→ Seed LBC/FT (référentiel + rôles + utilisateurs)")

    db = SessionLocal()
    try:
        print("  · rôles RBAC :", rbac_service.seed_roles(db))
        print("  · référentiel :", referentiel_service.seed_referentiel(db))
        print("  · règles d'alerte :", alerting_service.seed_rules(db))
    finally:
        db.close()

    # Tenant + utilisateurs : nécessite de contourner la RLS (comme l'auth applicative).
    with engine.begin() as conn:
        conn.execute(text(f"SET ROLE {settings.AUTH_BYPASS_ROLE}"))
        tenant_id = _ensure_tenant(conn)
        conf_uid = _ensure_user(conn, conf_email, "Cellule de Conformité", conf_pwd, tenant_id)
        ana_uid = _ensure_user(conn, ana_email, "Analyste", ana_pwd, tenant_id)
        conn.execute(text("RESET ROLE"))

    db = SessionLocal()
    try:
        rbac_service.assign_role(db, uuid.UUID(conf_uid), uuid.UUID(tenant_id), CONFORMITE_ROLE)
        rbac_service.assign_role(db, uuid.UUID(ana_uid), uuid.UUID(tenant_id), ANALYSTE_ROLE)
    finally:
        db.close()

    print("\n✅ Seed terminé.")
    print("   ┌── Identifiants ──────────────────────────────")
    print(f"   │ Conformité (accès complet) : {conf_email} / {conf_pwd}")
    print(f"   │ Analyste (Principal seul)  : {ana_email} / {ana_pwd}")
    print("   └──────────────────────────────────────────────")
    print("   ⚠️  Changez ces mots de passe après la première connexion.")


if __name__ == "__main__":
    main()
