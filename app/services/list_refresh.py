"""
Rafraîchissement des listes de sanctions et de PPE.

Remplace la stratégie « purge puis rechargement » de l'ancien agent autonome,
qui était inapplicable pour deux raisons :

1. `screening_matches.entity_id` référence `entities.id` SANS `ON DELETE`. Dès
   qu'une vérification avait rapproché une entité, sa suppression était
   refusée par la base — la mise à jour de la source échouait donc en entier,
   et de plus en plus souvent à mesure que la banque travaillait.
2. Même réussie, la purge réattribuait de nouveaux identifiants à chaque
   exécution. Les dossiers déjà décidés auraient pointé vers des entités
   disparues, ce qui est inacceptable pour un dispositif auditable : un
   dossier LBC/FT doit pouvoir se relire tel qu'il se présentait à la décision.

Le principe retenu est donc : on n'efface jamais, on RADIE. Une personne
retirée d'une liste est une information de conformité à conserver, pas une
ligne à supprimer.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Iterable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import list_ingest
from app.services.matching import normalize_name, tokenize

logger = logging.getLogger("simandou.list_refresh")

# Garde-fou contre la radiation en masse. Si une source ne renvoie qu'une
# fraction de son volume habituel — fichier tronqué, portail en panne, format
# changé — radier tout ce qui manque viderait la liste. On préfère alors ne
# rien radier et signaler l'anomalie : une sous-couverture silencieuse est le
# pire scénario pour un dispositif de sanctions.
MIN_COVERAGE_RATIO = 0.80

# Recouvrement minimal entre les références fraîches et celles déjà en base.
# Si un adaptateur change de convention d'identifiant — « OFAC-6636 » au lieu
# de « OFAC-SDN-6636 » —, AUCUNE référence ne se retrouve : le moteur croirait
# à 18 000 inscriptions nouvelles et à 18 000 radiations simultanées, doublant
# la base et éteignant la liste réelle. Ce cas s'est présenté : les listes
# ONU / OFAC / UE avaient été chargées par des scripts ponctuels dont la
# convention différait de celle des adaptateurs.
MIN_REF_OVERLAP = 0.50


class RefConventionMismatch(RuntimeError):
    """Les références fraîches ne correspondent pas à celles déjà en base."""


def _source_id(db: Session, code: str) -> Optional[int]:
    return db.execute(
        text("SELECT id FROM sources WHERE source_code = :c"), {"c": code}
    ).scalar()


def refresh_source(
    db: Session,
    *,
    source_code: str,
    source_name: str,
    records: Iterable[dict],
    record_type: str = "SANCTION",
    risk_level: str = "HIGH",
    source_type: str = "SANCTIONS",
    allow_delisting: bool = True,
    dry_run: bool = False,
    force: bool = False,
) -> dict:
    """
    Aligne la base sur le contenu frais d'une source.

    - référence absente en base   → création
    - référence présente          → mise à jour du nom principal et des alias
                                     si nécessaire, et réactivation si l'entité
                                     avait été radiée à tort
    - référence disparue du flux  → radiation (`unlisted_on`), jamais suppression
    """
    today = dt.date.today()
    src_id = list_ingest.get_or_create_source(
        db, code=source_code, name=source_name, source_type=source_type
    )

    # État actuel : référence d'origine → (identifiant d'entité, date de radiation)
    existing: dict[str, tuple[str, Optional[dt.date]]] = {
        r["source_ref"]: (str(r["entity_id"]), r["unlisted_on"])
        for r in db.execute(text("""
            SELECT source_ref, entity_id, unlisted_on
              FROM source_records WHERE source_id = :s
        """), {"s": src_id}).mappings()
    }

    # Le flux est matérialisé pour pouvoir contrôler la convention
    # d'identifiants AVANT d'écrire quoi que ce soit.
    frais = [r for r in records
             if str(r.get("source_ref") or "").strip()
             and (r.get("primary_name") or "").strip()]
    refs_frais = {str(r["source_ref"]).strip() for r in frais}

    recouvrement = 1.0
    if existing and refs_frais:
        recouvrement = len(refs_frais & set(existing)) / len(refs_frais)
        if recouvrement < MIN_REF_OVERLAP and not force and not dry_run:
            raise RefConventionMismatch(
                f"{source_code} : seules {recouvrement:.0%} des références reçues "
                f"correspondent aux {len(existing)} déjà en base. La convention "
                f"d'identifiants a probablement changé — écriture refusée pour ne "
                f"pas dupliquer la source et radier l'existant."
            )

    if dry_run:
        return {
            "source": source_code, "source_id": src_id, "dry_run": True,
            "fresh": len(refs_frais), "existing": len(existing),
            "overlap": round(recouvrement, 4),
            "would_create": len(refs_frais - set(existing)),
            "would_delist": len({r for r, (_, u) in existing.items() if u is None} - refs_frais),
            # Échantillons des deux conventions : sans eux, réconcilier une
            # source revient à deviner le format attendu.
            "sample_existing": sorted(existing)[:4],
            "sample_fresh": sorted(refs_frais)[:4],
        }

    seen: set[str] = set()
    reinscrites: set[str] = set()
    to_create: list[dict] = []
    created = updated = relisted = unchanged = 0

    for rec in frais:
        ref = str(rec.get("source_ref") or "").strip()
        primary = (rec.get("primary_name") or "").strip()
        if not ref or not primary:
            continue
        if ref in seen:          # doublon dans le flux amont
            continue
        seen.add(ref)

        hit = existing.get(ref)
        if hit is None:
            # Les créations sont accumulées puis confiées EN UNE FOIS au moteur
            # d'ingestion : l'appeler ligne à ligne rechargerait à chaque fois
            # la liste des références existantes, soit un coût quadratique sur
            # les 18 000 entrées de l'OFAC.
            to_create.append(rec)
        else:
            entity_id, unlisted = hit
            changed = _update(db, entity_id, rec)
            if unlisted is not None:
                # Réinscrite après une radiation : le cas existe (levée de
                # sanction annulée, correction d'un retrait).
                db.execute(text("""
                    UPDATE source_records SET unlisted_on = NULL
                     WHERE source_id = :s AND source_ref = :r
                """), {"s": src_id, "r": ref})
                relisted += 1
                reinscrites.add(ref)
            elif changed:
                updated += 1
            else:
                unchanged += 1

        if updated and updated % list_ingest.BATCH == 0:
            db.commit()

    db.commit()

    if to_create:
        out_new = list_ingest.ingest(
            db,
            source_code=source_code,
            source_name=source_name,
            records=to_create,
            record_type=record_type,
            risk_level=risk_level,
            source_type=source_type,
        )
        created = int(out_new.get("created") or 0)

    # ── Radiation des références disparues ───────────────────────────────────
    actifs = {r for r, (_, u) in existing.items() if u is None}
    disparus = actifs - seen
    delisted = 0
    skipped_delisting = False

    if actifs and len(seen) < MIN_COVERAGE_RATIO * len(actifs):
        # Le flux couvre trop peu : on ne radie rien.
        skipped_delisting = True
        logger.warning(
            "list_refresh_coverage_too_low",
            extra={"source": source_code, "fresh_count": len(seen),
                   "active_count": len(actifs)},
        )
    elif allow_delisting and disparus:
        for chunk in _chunks(sorted(disparus), 500):
            db.execute(text("""
                UPDATE source_records SET unlisted_on = :d
                 WHERE source_id = :s AND source_ref = ANY(:refs)
                   AND unlisted_on IS NULL
            """), {"d": today, "s": src_id, "refs": chunk})
        db.commit()
        delisted = len(disparus)

    # Entités nouvellement inscrites ou réinscrites : ce sont elles, et elles
    # seules, qu'il faut confronter au portefeuille déjà connu.
    nouvelles: list[str] = []
    refs_neuves = sorted((seen - set(existing)) | reinscrites)
    for chunk in _chunks(refs_neuves, 500):
        nouvelles += [str(r) for r in db.execute(text("""
            SELECT entity_id FROM source_records
             WHERE source_id = :s AND source_ref = ANY(:refs)
        """), {"s": src_id, "refs": chunk}).scalars()]

    # Le rapprochement met ses candidats en cache cinq minutes. Après une
    # mise à jour de liste, servir un résultat périmé — radié encore signalé,
    # nouvelle inscription encore absente — est exactement ce qu'un dispositif
    # de sanctions ne doit pas faire.
    try:
        from app.services.matching import invalidate_matching_cache
        invalidate_matching_cache()
    except Exception:
        logger.exception("matching_cache_invalidation_failed")

    out = {
        "source": source_code, "source_id": src_id,
        "new_entity_ids": nouvelles,
        "fresh": len(seen), "created": created, "updated": updated,
        "relisted": relisted, "unchanged": unchanged,
        "delisted": delisted, "delisting_skipped": skipped_delisting,
    }
    logger.info("list_refresh_done", extra={"result": out})
    return out


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _update(db: Session, entity_id: str, rec: dict) -> bool:
    """
    Met à jour l'entité SANS changer son identifiant.

    C'est là tout l'intérêt de la fusion : les correspondances déjà
    historisées continuent de désigner la même personne.
    """
    primary = (rec.get("primary_name") or "").strip().upper()
    current = db.execute(text("SELECT primary_name FROM entities WHERE id = CAST(:i AS uuid)"),
                         {"i": entity_id}).scalar()
    if (current or "") == primary:
        return False

    db.execute(text("""
        UPDATE entities SET primary_name = :n, updated_at = now()
         WHERE id = CAST(:i AS uuid)
    """), {"n": primary, "i": entity_id})
    # Le nom principal a changé : on remplace les libellés, en conservant
    # l'entité et donc l'historique qui s'y rattache.
    db.execute(text("DELETE FROM entity_names WHERE entity_id = CAST(:i AS uuid)"),
               {"i": entity_id})
    _add_name(db, entity_id, rec.get("primary_name") or "", True)
    pnorm = normalize_name(rec.get("primary_name") or "")
    for alias in dict.fromkeys(rec.get("aliases") or []):
        if alias and normalize_name(alias) != pnorm:
            _add_name(db, entity_id, alias, False)
    return True


def _add_name(db: Session, entity_id: str, value: str, is_primary: bool) -> None:
    value = (value or "").strip()
    if not value:
        return
    norm = normalize_name(value)
    db.execute(text("""
        INSERT INTO entity_names
            (entity_id, name_raw, name_normalized, name_tokens, is_primary, name_type)
        VALUES (CAST(:e AS uuid), :raw, :norm, :tok, :prim, :typ)
    """), {"e": entity_id, "raw": value, "norm": norm, "tok": tokenize(norm),
           "prim": is_primary, "typ": "PRIMARY" if is_primary else "ALIAS"})
