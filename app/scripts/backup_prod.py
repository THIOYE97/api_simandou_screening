"""
Sauvegarde quotidienne de la base de production — export logique daté.

Le plan Render pro fournit déjà des sauvegardes physiques automatiques (reprise
rapide, restauration point-dans-le-temps). Ce script les COMPLÈTE par un export
logique téléchargeable : une copie portable, hors Render, qu'un dossier BCRG
peut archiver et vérifier. Une sauvegarde qu'on ne peut pas produire à la
demande et constater n'en est pas une.

Déclenché par un cron Render (voir render.yaml). Envoie une trace Brevo à la
Conformité avec l'horodatage et l'URL de téléchargement de l'export.

Variables d'environnement :
  RENDER_API_KEY     clé API Render (compte). SANS elle, le script s'abstient
                     proprement (comme Brevo) plutôt que d'échouer.
  RENDER_PROD_DB_ID  identifiant de la base de production (dpg-…).
  BREVO_*            configuration SMTP pour la trace (partagée avec les listes).

⚠ La clé API Render est à portée COMPTE : la stocker ici donne au cron un accès
  complet. À n'activer qu'en connaissance de cause ; à faire tourner/retirer si
  Render introduit un jour des clés à portée réduite.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timezone

import httpx

from app.services import list_notifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backup_prod")

RENDER_API = "https://api.render.com/v1"
API_KEY = os.getenv("RENDER_API_KEY")
DB_ID = os.getenv("RENDER_PROD_DB_ID")

# Fenêtre d'attente : un export logique met quelques minutes à apparaître.
POLL_TIMEOUT_S = 600
POLL_INTERVAL_S = 20


def _headers() -> dict:
    return {"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"}


def _list_exports() -> list[dict]:
    r = httpx.get(f"{RENDER_API}/postgres/{DB_ID}/export", headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json() or []


def _trigger_export() -> None:
    r = httpx.post(f"{RENDER_API}/postgres/{DB_ID}/export", headers=_headers(), timeout=30)
    # 201/202 selon l'état ; on tolère, l'apparition dans la liste fait foi.
    if r.status_code >= 400:
        raise RuntimeError(f"déclenchement refusé : HTTP {r.status_code} {r.text[:200]}")


def _notify(ok: bool, detail: str, url: str | None = None) -> None:
    ts = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    etat, couleur = ("SUCCÈS", "#15803d") if ok else ("ÉCHEC", "#b91c1c")
    lien = (f"<p style='margin-top:12px'><a href='{url}'>Télécharger l'export</a> "
            f"(lien signé, à durée limitée)</p>") if url else ""
    html = f"""
    <div style="font-family:system-ui,-apple-system,sans-serif;font-size:14px;color:#111">
      <h2 style="margin:0 0 4px">Sauvegarde de la base de production</h2>
      <p style="margin:0 0 12px;color:#555">{ts} ·
         <b style="color:{couleur}">{etat}</b></p>
      <p style="margin:0;color:#333">{detail}</p>
      {lien}
      <p style="margin-top:20px;color:#666;font-size:12px">
        Export logique complémentaire des sauvegardes physiques Render.
        Copie portable destinée à l'archivage de conformité.
      </p>
    </div>
    """
    try:
        list_notifier._send_brevo_smtp(f"[LBC/FT] Sauvegarde — {etat} — {ts}", html)
    except Exception:
        logger.exception("notification_failed")


def main() -> int:
    if not (API_KEY and DB_ID):
        logger.warning("RENDER_API_KEY / RENDER_PROD_DB_ID absents — sauvegarde ignorée.")
        return 0  # abstention propre, pas un échec

    started = datetime.now(timezone.utc)
    try:
        avant = {e.get("id") for e in _list_exports()}
        _trigger_export()
        logger.info("export déclenché ; attente de son apparition…")

        deadline = time.monotonic() + POLL_TIMEOUT_S
        nouveau = None
        while time.monotonic() < deadline:
            time.sleep(POLL_INTERVAL_S)
            for e in _list_exports():
                if e.get("id") not in avant:
                    nouveau = e
                    break
            if nouveau:
                break

        if not nouveau:
            _notify(False, "L'export a été déclenché mais n'est pas apparu dans le "
                           f"délai imparti ({POLL_TIMEOUT_S // 60} min). À vérifier "
                           "dans le tableau de bord Render.")
            logger.error("export non apparu dans le délai")
            return 1

        _notify(True, f"Export produit à {nouveau.get('createdAt')}.",
                url=nouveau.get("url"))
        logger.info("export disponible : %s", nouveau.get("id"))
        return 0

    except Exception as exc:  # noqa: BLE001
        _notify(False, f"Erreur pendant la sauvegarde : {exc}")
        logger.exception("backup_failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
