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
from typing import Optional

from sqlalchemy import text

from app.core.config import settings
from app.core.db import engine

ROLE = "SUPER_ADMIN"


def _bypass(conn) -> None:
    """RLS contourné : `users` est isolé par tenant, or on agit hors tenant."""
    conn.execute(text(f"SET ROLE {settings.AUTH_BYPASS_ROLE}"))


def _colonnes(conn) -> set[str]:
    """
    Colonnes réelles de `user_roles`, relevées en base et non déduites du modèle.

    Le modèle `app/models/user_role.py` déclare `id`, `tenant_id` et
    `created_at` ; la base de production n'a que `(user_id, role)`. Comme le
    schéma de test est construit depuis les modèles, l'écart est invisible en
    test et n'apparaît qu'à l'exécution. On écrit donc contre ce que la base
    contient, ce qui rend ce script valable sur les deux schémas.
    """
    return {
        r[0]
        for r in conn.execute(
            text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'user_roles'
            """)
        )
    }


def construire_insert(
    colonnes: set[str], *, user_id: str, tenant_id: Optional[str] = None
) -> tuple[str, dict]:
    """
    Construit l'INSERT adapté aux colonnes réellement présentes.

    Production : `(user_id, role)` seulement. Base créée depuis les modèles :
    `id` et `tenant_id` en plus, tous deux NOT NULL. Une seule requête écrite
    en dur ne peut pas satisfaire les deux — d'où cette construction.
    """
    if not {"user_id", "role"} <= colonnes:
        raise RuntimeError("Table `user_roles` inattendue : colonnes user_id/role absentes.")

    champs = ["user_id", "role"]
    valeurs = ["CAST(:uid AS uuid)", f"'{ROLE}'"]
    params: dict = {"uid": str(user_id)}

    if "id" in colonnes:
        champs.insert(0, "id")
        valeurs.insert(0, "gen_random_uuid()")
    if "tenant_id" in colonnes:
        champs.append("tenant_id")
        valeurs.append("CAST(:tid AS uuid)")
        params["tid"] = str(tenant_id) if tenant_id else None

    return (
        f"INSERT INTO public.user_roles ({', '.join(champs)}) "
        f"VALUES ({', '.join(valeurs)})",
        params,
    )


def lister() -> int:
    with engine.begin() as conn:
        _bypass(conn)
        date_dispo = "created_at" in _colonnes(conn)
        depuis = "ur.created_at" if date_dispo else "NULL::timestamptz"
        rows = conn.execute(
            text(f"""
                SELECT u.email, u.full_name, {depuis} AS depuis
                FROM public.user_roles ur
                JOIN public.users u ON u.id = ur.user_id
                WHERE ur.role::text = '{ROLE}'
                ORDER BY u.email
            """)
        ).mappings().all()

    if not rows:
        print("Aucun super-administrateur déclaré.")
        return 0
    print(f"{len(rows)} super-administrateur(s) :")
    for r in rows:
        quand = f"  depuis le {r['depuis']:%d/%m/%Y}" if r["depuis"] else ""
        print(f"  · {r['email']}  ({r['full_name']}){quand}")
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

        if revoke:
            n = conn.execute(
                text(f"""
                    DELETE FROM public.user_roles
                    WHERE user_id = CAST(:uid AS uuid) AND role::text = '{ROLE}'
                """),
                {"uid": row["id"]},
            ).rowcount
            print(f"✓ SUPER_ADMIN retiré à {email}" if n else f"= {email} n'était pas SUPER_ADMIN")
            print("→ Effectif à la prochaine connexion (la revendication est dans le jeton).")
            return 0

        deja = conn.execute(
            text(f"""
                SELECT 1 FROM public.user_roles
                WHERE user_id = CAST(:uid AS uuid) AND role::text = '{ROLE}'
            """),
            {"uid": row["id"]},
        ).first()
        if deja:
            print(f"= {email} est déjà super-administrateur.")
            return 0

        cols = _colonnes(conn)
        if "tenant_id" in cols and not row["tenant_id"]:
            print(f"✗ {email} n'est rattaché à aucun tenant — rattachez-le d'abord.")
            return 1

        sql, params = construire_insert(cols, user_id=row["id"], tenant_id=row["tenant_id"])
        conn.execute(text(sql), params)
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
