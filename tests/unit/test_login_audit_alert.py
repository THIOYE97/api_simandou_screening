"""
Tests unitaires du courriel d'alerte de connexion (aucune base, aucun réseau).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services import login_audit_service as svc

pytestmark = pytest.mark.unit


def _event(**kw) -> dict:
    base = {
        "email": "conformite@bcrg-guinee.org",
        "ip": "41.82.10.5",
        "user_agent": "Mozilla/5.0",
        "created_at": datetime(2026, 8, 7, 9, 30, tzinfo=timezone.utc),
        "is_new_context": True,
        "is_first_login": False,
        "new_ip": True,
        "new_device": False,
    }
    base.update(kw)
    return base


class TestMotif:
    def test_premiere_connexion_prime_sur_le_reste(self):
        assert svc._motif(_event(is_first_login=True, new_ip=True, new_device=True)) == \
            "première connexion de ce compte"

    def test_ip_seule(self):
        assert svc._motif(_event()) == "adresse IP jamais vue"

    def test_ip_et_appareil(self):
        m = svc._motif(_event(new_device=True))
        assert "adresse IP" in m and "appareil" in m


class TestCourriel:
    def test_sujet_et_corps_portent_les_faits(self):
        sujet, html = svc.build_alert_email(_event(), full_name="Cellule de Conformité")
        assert "Cellule de Conformité" in sujet
        assert "41.82.10.5" in html
        assert "07/08/2026" in html
        assert "conformite@bcrg-guinee.org" in html

    def test_repli_sur_l_adresse_si_nom_absent(self):
        sujet, _ = svc.build_alert_email(_event())
        assert "conformite@bcrg-guinee.org" in sujet


class TestGardeFous:
    def test_rien_a_notifier_si_contexte_connu(self, monkeypatch):
        appels = []
        monkeypatch.setattr(svc, "_alert_recipients", lambda: appels.append("lu") or "x@y.z")
        svc.notify_new_context(_event(is_new_context=False))
        assert appels == [], "un contexte connu ne doit même pas chercher de destinataire"

    def test_desactivable_par_variable_d_environnement(self, monkeypatch):
        monkeypatch.setenv("LOGIN_ALERT_ENABLED", "false")
        assert svc._alert_enabled() is False
        monkeypatch.setenv("LOGIN_ALERT_ENABLED", "true")
        assert svc._alert_enabled() is True

    def test_sans_destinataire_aucun_envoi(self, monkeypatch):
        monkeypatch.delenv("LOGIN_ALERT_TO_EMAIL", raising=False)
        monkeypatch.delenv("BREVO_TO_EMAIL", raising=False)
        # Ne doit pas lever : l'absence de configuration n'est pas une erreur.
        svc.notify_new_context(_event())

    def test_une_panne_d_envoi_reste_silencieuse(self, monkeypatch):
        monkeypatch.setenv("LOGIN_ALERT_TO_EMAIL", "audit@bcrg-guinee.org")

        from app.services import list_notifier

        def _boom(*a, **k):
            raise RuntimeError("SMTP down")

        monkeypatch.setattr(list_notifier, "send_html_email", _boom)
        svc.notify_new_context(_event())  # ne doit pas lever
