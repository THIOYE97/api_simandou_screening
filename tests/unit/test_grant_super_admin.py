"""
L'INSERT du script d'attribution doit s'adapter au schéma rencontré.

La production n'a que `(user_id, role)` ; une base créée depuis les modèles a
en plus `id` et `tenant_id`, tous deux NOT NULL. Une requête écrite en dur ne
peut pas satisfaire les deux — et comme le schéma de test vient des modèles,
seul un test sur les colonnes attrape l'écart.
"""
from __future__ import annotations

import pytest

from app.scripts.grant_super_admin import construire_insert

pytestmark = pytest.mark.unit

PROD = {"user_id", "role"}
MODELES = {"id", "tenant_id", "user_id", "role", "created_at"}


class TestSchemaProduction:
    def test_n_insere_que_les_colonnes_existantes(self):
        sql, params = construire_insert(PROD, user_id="u-1", tenant_id="t-1")
        assert "user_roles (user_id, role)" in sql
        assert "id" not in sql.split("VALUES")[0].replace("user_id", "")
        assert "tenant_id" not in sql
        assert params == {"uid": "u-1"}

    def test_le_tenant_n_est_pas_transmis(self):
        _, params = construire_insert(PROD, user_id="u-1", tenant_id="t-1")
        assert "tid" not in params, "un paramètre non utilisé ferait échouer psycopg"


class TestSchemaModeles:
    def test_ajoute_id_et_tenant(self):
        sql, params = construire_insert(MODELES, user_id="u-1", tenant_id="t-1")
        assert "gen_random_uuid()" in sql
        assert "tenant_id" in sql
        assert params == {"uid": "u-1", "tid": "t-1"}

    def test_ordre_champs_et_valeurs_coherent(self):
        sql, _ = construire_insert(MODELES, user_id="u-1", tenant_id="t-1")
        champs = sql.split("(", 1)[1].split(")", 1)[0].split(", ")
        valeurs = sql.split("VALUES (", 1)[1].rstrip(")").split(", ")
        assert len(champs) == len(valeurs)
        assert champs[0] == "id" and valeurs[0] == "gen_random_uuid()"


class TestGardeFou:
    def test_table_inattendue_refusee(self):
        with pytest.raises(RuntimeError, match="user_roles"):
            construire_insert({"machin", "truc"}, user_id="u-1")

    def test_role_toujours_super_admin(self):
        for cols in (PROD, MODELES):
            sql, _ = construire_insert(cols, user_id="u-1", tenant_id="t-1")
            assert "'SUPER_ADMIN'" in sql
