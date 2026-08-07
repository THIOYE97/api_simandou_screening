"""
Attribution (ou retrait) du rôle SUPER_ADMIN à un compte.

Le super-administrateur est le seul profil qui voit au-delà d'un tenant :
bascule de tenant (`X-Tenant-Id`), contexte RLS élargi, et console de sécurité
(`/security/*`). Il ne s'attribue donc pas depuis l'interface — c'est une
opération d'exploitation, tracée par ce script.

    python -m app.scripts.grant_super_admin conformite@bcrg-guinee.org
    python -m app.scripts.grant_super_admin conformite@bcrg-guinee.org --revoke
    python -m app.scripts.grant_super_admin --list

Le rôle est écrit dans `user_roles` (table des rôles structurels), et non dans
`rbac_user_roles` (habilitations paramétrables par tenant) : c'est cette
première table que lit l'émission du jeton.

Prendre effet exige une NOUVELLE connexion : la revendication est portée par
l'access token, pas relue à chaque requête.
"""
from __future__ import annotations

import sys

from sqlalchemy import text

from app.core.config import settings
from app.core.db import engine

ROLE = "SUPER_ADMIN"


def _bypass(conn) -> None:
    """RLS contourné : `users` est isolé par tenant, or on agit hors tenant."""
    conn.execute(text(f"SET ROLE {settings.AUTH_BYPASS_ROLE}"))


def lister() -> int:
    with engine.begin() as conn:
        _bypass(conn)
        rows = conn.execute(
            text(f"""
                SELECT u.email, u.full_name, ur.created_at
                FROM public.user_roles ur
                JOIN public.users u ON u.id = ur.user_id
                WHERE ur.role = '{ROLE}'
                ORDER BY ur.created_at
            """)
        ).mappings().all()

    if not rows:
        print("Aucun super-administrateur déclaré.")
        return 0
    print(f"{len(rows)} super-administrateur(s) :")
    for r in rows:
        print(f"  · {r['email']}  ({r['full_name']})  depuis le {r['created_at']:%d/%m/%Y}")
    return 0


def appliquer(email: str, *, revoke: bool) -> int:
    with engine.begin() as conn:
        _bypass(conn)

        row = conn.execute(
            text("""
                SELECT id::text AS id, tenant_id::text AS tenant_id, full_name
                FROM public.users
                WHERE lower(trim(email)) = lower(trim(:e))
            """),
            {"e": email},
        ).mappings().first()

        if not row:
            print(f"✗ Aucun compte pour {email}")
            return 1
        if not row["tenant_id"]:
            print(f"✗ {email} n'est rattaché à aucun tenant — rattachez-le d'abord.")
            return 1

        if revoke:
            n = conn.execute(
                text(f"""
                    DELETE FROM public.user_roles
                    WHERE user_id = CAST(:uid AS uuid) AND role = '{ROLE}'
                """),
                {"uid": row["id"]},
            ).rowcount
            print(f"✓ SUPER_ADMIN retiré à {email}" if n else f"= {email} n'était pas SUPER_ADMIN")
        else:
            conn.execute(
                text(f"""
                    INSERT INTO public.user_roles (id, tenant_id, user_id, role)
                    VALUES (gen_random_uuid(), CAST(:tid AS uuid), CAST(:uid AS uuid), '{ROLE}')
                    ON CONFLICT (tenant_id, user_id, role) DO NOTHING
                """),
                {"tid": row["tenant_id"], "uid": row["id"]},
            )
            print(f"✓ {email} ({row['full_name']}) est super-administrateur.")

    print("→ Effectif à la prochaine connexion (la revendication est dans le jeton).")
    return 0


def main() -> int:
    args = [a for a in sys.argv[1:] if a]
    if not args or "--list" in args:
        return lister()

    revoke = "--revoke" in args
    emails = [a for a in args if not a.startswith("--")]
    if len(emails) != 1:
        print(__doc__)
        return 2
    return appliquer(emails[0], revoke=revoke)


if __name__ == "__main__":
    raise SystemExit(main())
