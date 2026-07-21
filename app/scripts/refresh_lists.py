"""
Rafraîchissement quotidien des listes — point d'entrée du Cron Job.

Remplace l'agent autonome « sanctions_agent », dont la stratégie de purge
échouait dès qu'une vérification avait rapproché une entité, et qui ne
couvrait que trois des huit sources.

Exécuté par un Cron Job Render sur l'image du back-end, et non par un fil
d'exécution dans le serveur web : rafraîchir huit sources prend plusieurs
minutes et consomme de la mémoire à analyser les XML. Dans le processus web,
cela monopoliserait un créneau de requête sur deux et pourrait faire tomber
l'API — l'API s'arrêterait parce qu'une liste se met à jour.

    python -m app.scripts.refresh_lists            # toutes les sources
    python -m app.scripts.refresh_lists UK CA      # sélection
    python -m app.scripts.refresh_lists --dry-run  # simulation, sans écriture
"""
from __future__ import annotations

import logging
import sys
import time

from app.core.db import SessionLocal
from app.services import (list_adapters, list_notifier, list_refresh,
                          list_rescreen)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("simandou.refresh_lists")


def _selectable() -> dict[str, dict]:
    """
    Sources rafraîchissables sans intervention humaine.

    L'Australie est écartée : son portail refuse les requêtes venant d'un
    serveur (protection anti-robot), le fichier doit être déposé à la main.
    Le Journal Officiel guinéen l'est aussi : il s'importe édition par
    édition, pas en flux complet.
    """
    out = {}
    for code, a in list_adapters.ADAPTERS.items():
        if a.get("upload_only") or a.get("accepts"):
            continue
        out[code] = a
    return out


def main(argv: list[str]) -> int:
    args = argv[1:]
    # La simulation permet de contrôler la convention d'identifiants et le
    # volume attendu AVANT d'écrire quoi que ce soit sur une base réelle.
    dry = "--dry-run" in args
    demandees = [c.upper() for c in args if not c.startswith("-")] or None
    sources = _selectable()
    if demandees:
        inconnues = [c for c in demandees if c not in list_adapters.ADAPTERS]
        if inconnues:
            print(f"Source(s) inconnue(s) : {', '.join(inconnues)}", file=sys.stderr)
            print(f"Disponibles : {', '.join(sorted(list_adapters.ADAPTERS))}", file=sys.stderr)
            return 2
        sources = {c: list_adapters.ADAPTERS[c] for c in demandees}

    resultats: list[dict] = []
    echecs: list[str] = []
    debut = time.monotonic()

    for code, adapter in sorted(sources.items()):
        t0 = time.monotonic()
        db = SessionLocal()
        try:
            logger.info("refresh_start", extra={"source": code})
            records = adapter["fetch"]()
            res = list_refresh.refresh_source(
                db,
                source_code=code,
                source_name=adapter["name"],
                records=records,
                record_type=adapter.get("record_type", "SANCTION"),
                risk_level=adapter.get("risk_level", "HIGH"),
                source_type=adapter.get("source_type", "SANCTIONS"),
                dry_run=dry,
            )
            if dry:
                res["duration_s"] = round(time.monotonic() - t0, 1)
                resultats.append(res)
                continue
            # Exigence TDR : re-profiler le portefeuille à chaque mise à jour.
            # Un échec ici ne doit pas invalider un rafraîchissement réussi.
            try:
                res["rescreen"] = list_rescreen.rescreen_for_entities(
                    db, res.get("new_entity_ids") or [], source_code=code
                )
            except Exception:
                logger.exception("rescreen_failed", extra={"source": code})
                res["rescreen"] = {"alerts": 0, "error": True}

            res["duration_s"] = round(time.monotonic() - t0, 1)
            res.pop("new_entity_ids", None)     # volumineux, inutile au rapport
            resultats.append(res)
        except list_refresh.RefConventionMismatch as e:
            db.rollback()
            echecs.append(f"{code} (convention d'identifiants)")
            logger.error("refresh_ref_mismatch", extra={"source": code, "reason": str(e)})
        except Exception as e:
            db.rollback()
            echecs.append(code)
            # Une source en échec ne doit pas empêcher les autres : c'est tout
            # l'intérêt de traiter chaque source dans sa propre session.
            logger.exception("refresh_failed", extra={"source": code, "reason": str(e)[:200]})
        finally:
            db.close()

    # Compte rendu à la Conformité : elle doit garder une trace écrite de
    # chaque mise à jour, y compris des échecs.
    if dry:
        print("\n─── Simulation (aucune écriture) ───")
        for r in resultats:
            drapeau = "  ⛔ REFUSE" if r["overlap"] < list_refresh.MIN_REF_OVERLAP else "  ✅"
            print(f"  {r['source']:<8} reçues={r['fresh']:>7}  en base={r['existing']:>7}  "
                  f"recouvrement={r['overlap']:>6.1%}  "
                  f"créerait={r['would_create']:>6}  radierait={r['would_delist']:>6}{drapeau}")
            if r["overlap"] < list_refresh.MIN_REF_OVERLAP:
                print(f"             en base : {r['sample_existing']}")
                print(f"             reçues  : {r['sample_fresh']}")
        if echecs:
            print(f"\n  ⚠ refusées : {', '.join(echecs)}")
        return 0

    list_notifier.notify_refresh(resultats, echecs, time.monotonic() - debut)

    print("\n─── Rafraîchissement des listes ───")
    for r in resultats:
        alertes = (r.get("rescreen") or {}).get("alerts", 0)
        print(f"  {r['source']:<8} {r['fresh']:>7} reçues · "
              f"{r['created']:>5} nouvelles · {r['updated']:>5} modifiées · "
              f"{r['relisted']:>4} réinscrites · {r['delisted']:>5} radiées · "
              f"{alertes:>3} alertes · {r['duration_s']}s"
              + ("  ⚠ radiation suspendue (couverture trop faible)"
                 if r.get("delisting_skipped") else ""))
    if echecs:
        print(f"\n  ⚠ sources en échec : {', '.join(echecs)}")

    # Code de sortie non nul si TOUT a échoué : le cron doit alerter.
    # Un échec partiel reste un succès — les autres sources sont à jour.
    return 1 if (echecs and not resultats) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
