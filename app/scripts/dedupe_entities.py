"""
Doublons d'entités laissés par l'ancien agent de sanctions.

L'agent écrivait dans `entities` sans jamais alimenter `source_records` : il
identifiait ses lignes par une colonne texte `entities.source_name`, quand le
moteur d'ingestion du back-end passe par la table `sources`. Les deux ont donc
chargé les mêmes listes en parallèle, chacun créant ses propres entités.

Conséquence visible : « Vladimir Vladimirovich PUTIN » existe en double, et une
vérification renvoie deux correspondances à 100 % pour la même personne.

L'agent est arrêté ; ce script traite ce qu'il a laissé. Il ne supprime QUE des
entités orphelines — sans enregistrement de source et sans aucune référence
ailleurs. Toute entité citée par un dossier, une alerte ou une correspondance
historisée est conservée : un dossier LBC/FT doit rester relisible tel qu'il se
présentait à la décision.

    python -m app.scripts.dedupe_entities             # analyse seule
    python -m app.scripts.dedupe_entities --apply     # suppression effective
"""
from __future__ import annotations

import logging
import sys

from sqlalchemy import text

from app.core.db import SessionLocal

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("simandou.dedupe")

# Tables susceptibles de citer une entité. Toutes n'existent pas partout :
# plusieurs sont antérieures aux modèles ORM et absentes des bases reconstruites
# à partir d'eux. On interroge donc le catalogue plutôt que de les énumérer en
# dur — une table absente ne peut rien référencer, l'ignorer est sans risque.
#
# Et si l'une venait à manquer par erreur, la base refuserait la suppression :
# les clés étrangères restent le garde-fou ultime.
_TABLES_REFERENTES = (
    "source_records", "screening_matches", "case_alerts", "case_entities",
    "companies", "persons", "external_identities", "person_attributes",
)


def _condition_referencee(db) -> str:
    presentes = {r for r in db.execute(text("""
        SELECT table_name FROM information_schema.tables
         WHERE table_schema = 'public' AND table_name = ANY(:noms)
    """), {"noms": list(_TABLES_REFERENTES)}).scalars()}
    clauses = [f"EXISTS (SELECT 1 FROM {t} x WHERE x.entity_id = e.id)"
               for t in _TABLES_REFERENTES if t in presentes]
    return " OR ".join(clauses) if clauses else "FALSE"


def _sql_candidats(db) -> str:
    """
    Candidats : entités sans source NI référence, dont le nom est également
    porté par une entité rattachée à une source. Cette dernière condition
    garantit qu'on ne supprime rien d'unique — seulement des doublons dont la
    version rattachée à une source subsiste.
    """
    ref = _condition_referencee(db)
    return f"""
WITH orphelines AS (
    SELECT e.id, e.primary_name, e.entity_type::text AS entity_type,
           UPPER(TRIM(e.primary_name)) AS cle
      FROM entities e
     WHERE NOT ({ref})
),
officielles AS (
    SELECT DISTINCT UPPER(TRIM(e.primary_name)) AS cle
      FROM entities e
      JOIN source_records sr ON sr.entity_id = e.id
)
SELECT o.id, o.primary_name, o.entity_type
  FROM orphelines o
  JOIN officielles f ON f.cle = o.cle
"""


def analyser(db) -> dict:
    total = db.execute(text("SELECT COUNT(*) FROM entities")).scalar()
    sans_source = db.execute(text("""
        SELECT COUNT(*) FROM entities e
         WHERE NOT EXISTS (SELECT 1 FROM source_records x WHERE x.entity_id = e.id)
    """)).scalar()
    ref = _condition_referencee(db)
    protegees = db.execute(text(f"""
        SELECT COUNT(*) FROM entities e
         WHERE NOT EXISTS (SELECT 1 FROM source_records x WHERE x.entity_id = e.id)
           AND ({ref})
    """)).scalar()
    sql = _sql_candidats(db)
    candidats = db.execute(text(f"SELECT COUNT(*) FROM ({sql}) c")).scalar()
    exemples = db.execute(text(f"{sql} ORDER BY o.primary_name LIMIT 8")).mappings().all()
    return {"total": total, "sans_source": sans_source, "protegees": protegees,
            "candidats": candidats, "exemples": [dict(x) for x in exemples]}


def supprimer(db) -> int:
    """
    Supprime les doublons orphelins, par tranches.

    Les noms partent en cascade. Aucune autre table n'est touchée : par
    construction, aucune ne référence ces entités.
    """
    n = 0
    while True:
        ids = [str(r) for r in db.execute(text(
            f"SELECT o.id FROM ({_sql_candidats(db)}) o LIMIT 500")).scalars()]
        if not ids:
            break
        db.execute(text("DELETE FROM entities WHERE id = ANY(CAST(:ids AS uuid[]))"),
                   {"ids": ids})
        db.commit()
        n += len(ids)
        logger.info("dedupe_progress", extra={"supprimees": n})
    return n


def main(argv: list[str]) -> int:
    appliquer = "--apply" in argv[1:]
    db = SessionLocal()
    try:
        a = analyser(db)
        print("\n─── Doublons d'entités ───")
        print(f"  entités au total          : {a['total']:>7}")
        print(f"  sans enregistrement source: {a['sans_source']:>7}")
        print(f"  dont référencées ailleurs : {a['protegees']:>7}  (conservées)")
        print(f"  doublons supprimables     : {a['candidats']:>7}")
        if a["exemples"]:
            print("\n  exemples :")
            for x in a["exemples"]:
                print(f"    {str(x['primary_name'])[:46]:<46} [{x['entity_type']}]")

        if not appliquer:
            print("\n  (analyse seule — relancer avec --apply pour supprimer)")
            return 0

        if a["candidats"] == 0:
            print("\n  rien à supprimer.")
            return 0

        n = supprimer(db)
        reste = analyser(db)
        print(f"\n  {n} doublon(s) supprimé(s).")
        print(f"  entités restantes : {reste['total']}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
