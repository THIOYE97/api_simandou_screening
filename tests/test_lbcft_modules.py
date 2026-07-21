"""
Tests d'intégration des modules LBC/FT (TDR BCRG) :
- M1 Référentiel (seed pays/GAFI, scénarios)
- M7 Scoring (évaluation paramétrable + classification + historisation)
- M6 Alerte (détection depuis le scoring + cycle de vie)
- M5 KYT (ingestion transactions + structuring + Déclaration de soupçon)
- M8 Reportings + Interfaçage (SWIFT/T24)

Niveau service, sur Postgres jetable (testcontainers).

NB IMPORTANT : les imports `app.*` sont FAITS DANS LES TESTS (paresseux), pas en
tête de module. Le conftest `migrated_db` recharge tous les modules `app.*` pour
rebrancher la DATABASE_URL du testcontainer ; un import en tête figerait des
classes ORM sur un ancien registre SQLAlchemy (→ KeyError de résolution de
relations). Ce pattern est aligné sur les autres tests d'intégration du projet.
"""
from decimal import Decimal

import pytest


@pytest.mark.integration
def test_seed_referentiel(db):
    from app.services import referentiel_service
    created = referentiel_service.seed_referentiel(db)
    assert created["countries"] > 0
    assert created["scenarios"] == 9   # dont 2 scénarios bénéficiaires effectifs

    countries = referentiel_service.list_countries(db)
    iso = {c.iso_code for c in countries}
    assert "IR" in iso and "KP" in iso  # GAFI blacklist
    ir = next(c for c in countries if c.iso_code == "IR")
    assert ir.is_high_risk and ir.is_non_cooperative

    # idempotent
    again = referentiel_service.seed_referentiel(db)
    assert again["scenarios"] == 0


@pytest.mark.integration
def test_scoring_strong_sanction_is_critical(db):
    from app.models.scoring import RiskClass, SubjectType
    from app.services import referentiel_service, scoring_service
    referentiel_service.seed_referentiel(db)

    a = scoring_service.score_subject(
        db,
        subject_type=SubjectType.PERSON,
        context={"match_score": 92, "is_pep": True, "country": "IR"},
        subject_ref="client-001",
        subject_label="John Doe",
    )
    codes = {t["code"] for t in a.triggered}
    assert "SANCTION_MATCH_STRONG" in codes
    assert "PEP_HIT" in codes
    assert "GEO_NON_COOPERATIVE" in codes
    assert a.total_score == 100  # plafonné
    assert a.risk_class == RiskClass.CRITICAL

    hist = scoring_service.list_assessments(db, subject_ref="client-001")
    assert len(hist) == 1


@pytest.mark.integration
def test_low_risk_subject(db):
    from app.models.scoring import RiskClass, SubjectType
    from app.services import referentiel_service, scoring_service
    referentiel_service.seed_referentiel(db)
    a = scoring_service.score_subject(
        db,
        subject_type=SubjectType.PERSON,
        context={"match_score": 10, "country": "FR"},
    )
    assert a.risk_class == RiskClass.LOW
    assert a.triggered == []


@pytest.mark.integration
def test_scoring_generates_alerts_and_lifecycle(db):
    from app.models.alerting import AlertStatus
    from app.models.scoring import SubjectType
    from app.services import alerting_service, referentiel_service, scoring_service
    referentiel_service.seed_referentiel(db)
    alerting_service.seed_rules(db)

    a = scoring_service.score_subject(
        db,
        subject_type=SubjectType.PERSON,
        context={"match_score": 92, "country": "IR"},
        subject_ref="client-002",
    )
    alerts = alerting_service.generate_from_assessment(db, a)
    assert len(alerts) >= 1
    escalated = [x for x in alerts if x.status == AlertStatus.ESCALATED]
    assert escalated, "un scénario CRITICAL doit escalader automatiquement"

    open_alerts = alerting_service.list_alerts(db, status=AlertStatus.OPEN)
    if open_alerts:
        closed = alerting_service.transition_status(
            db, open_alerts[0].id, AlertStatus.CLOSED_FALSE_POSITIVE,
            resolution="Homonymie confirmée : date de naissance et nationalité différentes.",
        )
        assert closed.status == AlertStatus.CLOSED_FALSE_POSITIVE
        assert closed.resolved_at is not None


@pytest.mark.integration
def test_invalid_transition_rejected(db):
    from fastapi import HTTPException

    from app.models.alerting import AlertStatus
    from app.models.scoring import SubjectType
    from app.services import alerting_service, referentiel_service, scoring_service
    referentiel_service.seed_referentiel(db)
    alerting_service.seed_rules(db)
    a = scoring_service.score_subject(
        db, subject_type=SubjectType.PERSON,
        context={"match_score": 92, "country": "IR"}, subject_ref="client-003",
    )
    alerts = alerting_service.generate_from_assessment(db, a)
    closed = alerting_service.transition_status(
        db, alerts[0].id, AlertStatus.CLOSED_TRUE_POSITIVE, resolution="confirmé"
    )
    with pytest.raises(HTTPException):
        alerting_service.transition_status(db, closed.id, AlertStatus.IN_REVIEW)


# --- M5 KYT ------------------------------------------------------------------

@pytest.mark.integration
def test_kyt_large_cash_flags_scenario(db):
    from app.models.kyt import Channel, SourceSystem
    from app.services import alerting_service, kyt_service, referentiel_service
    referentiel_service.seed_referentiel(db)
    alerting_service.seed_rules(db)
    txn, assessment, alerts = kyt_service.ingest_transaction(db, {
        "source_system": SourceSystem.T24,
        "channel": Channel.CASH,
        "amount": Decimal("15000"),
        "currency": "USD",
        "customer_ref": "cust-cash",
    })
    codes = {t["code"] for t in assessment.triggered}
    assert "TXN_LARGE_CASH" in codes
    assert txn.risk_assessment_id == assessment.id


@pytest.mark.integration
def test_kyt_structuring_detection(db):
    from app.models.kyt import Channel, SourceSystem
    from app.services import kyt_service, referentiel_service
    referentiel_service.seed_referentiel(db)
    last = None
    for _ in range(3):
        _, last, _ = kyt_service.ingest_transaction(db, {
            "source_system": SourceSystem.RTGS,
            "channel": Channel.WIRE,
            "amount": Decimal("6000"),
            "currency": "USD",
            "customer_ref": "cust-struct",
        })
    codes = {t["code"] for t in last.triggered}
    assert "BEHAVIOR_STRUCTURING" in codes, "le fractionnement doit être détecté au 3e mouvement"


@pytest.mark.integration
def test_sar_workflow(db):
    from fastapi import HTTPException

    from app.models.kyt import SARDecision, SARStatus
    from app.services import kyt_service
    sar = kyt_service.create_sar(db, {
        "subject_ref": "cust-sar",
        "reason": "Comportement atypique répété",
        "narrative": "Multiples dépôts espèces sous seuil.",
    })
    assert sar.status == SARStatus.DRAFT
    sar = kyt_service.update_sar(db, sar.id, status=SARStatus.SUBMITTED)
    sar = kyt_service.update_sar(db, sar.id, status=SARStatus.UNDER_REVIEW)
    sar = kyt_service.update_sar(db, sar.id, status=SARStatus.DECIDED, decision=SARDecision.FILED_TO_CENTIF)
    assert sar.status == SARStatus.DECIDED
    assert sar.decision == SARDecision.FILED_TO_CENTIF

    with pytest.raises(HTTPException):
        kyt_service.update_sar(db, sar.id, status=SARStatus.SUBMITTED)


# --- M8 Reportings -----------------------------------------------------------

@pytest.mark.integration
def test_reporting_dashboard_and_inventory(db):
    from app.models.scoring import SubjectType
    from app.services import (
        alerting_service,
        referentiel_service,
        reporting_service,
        scoring_service,
    )
    referentiel_service.seed_referentiel(db)
    alerting_service.seed_rules(db)
    a = scoring_service.score_subject(
        db, subject_type=SubjectType.PERSON,
        context={"match_score": 95, "country": "KP"}, subject_ref="hr-1", subject_label="Bad Actor",
    )
    alerting_service.generate_from_assessment(db, a)

    dash = reporting_service.dashboard(db)
    assert dash["assessments_by_risk_class"].get("CRITICAL", 0) >= 1

    inv = reporting_service.high_risk_subjects(db)
    assert any(s["subject_ref"] == "hr-1" and s["risk_class"] == "CRITICAL" for s in inv)


# --- Interfaçage (SWIFT / T24) ----------------------------------------------

@pytest.mark.integration
def test_swift_mt103_parsing_and_ingest(db):
    from app.services import kyt_service, referentiel_service
    from app.services.integration import parse_mt103
    referentiel_service.seed_referentiel(db)
    msg = ":20:REF123456\n:32A:250701USD15000,00\n:50K:ACME CORP\n:59:JOHN DOE\nKP\n"
    data = parse_mt103(msg)
    assert data["currency"] == "USD"
    assert str(data["amount"]) == "15000.00"
    assert data["external_ref"] == "REF123456"

    txn, assessment, _ = kyt_service.ingest_transaction(db, data)
    assert txn.source_system.value == "SWIFT"
    assert txn.risk_assessment_id == assessment.id


# --- Adverse media -----------------------------------------------------------

@pytest.mark.integration
def test_adverse_media_screen(db):
    from app.services import adverse_media_service
    adverse_media_service.seed_adverse_media(db)

    # nom proche (faute/variation) → doit matcher
    hits = adverse_media_service.screen_name(db, "Viktor Petrov")
    assert hits and hits[0]["category"] == "MONEY_LAUNDERING"
    assert hits[0]["score"] >= 85

    # nom sans rapport → aucun match
    assert adverse_media_service.screen_name(db, "Marie Dupont Landerneau") == []


@pytest.mark.integration
def test_adverse_media_feeds_scoring(db):
    from app.models.scoring import SubjectType
    from app.services import referentiel_service, scoring_service
    referentiel_service.seed_referentiel(db)
    a = scoring_service.score_subject(
        db, subject_type=SubjectType.PERSON,
        context={"adverse_media_hit": True}, subject_ref="am-1",
    )
    codes = {t["code"] for t in a.triggered}
    assert "ADVERSE_MEDIA_HIT" in codes


# --- M2 RBAC -----------------------------------------------------------------

@pytest.mark.integration
def test_rbac_seed_and_effective_permissions(db):
    import uuid

    from sqlalchemy import text

    from app.services import rbac_service
    n = rbac_service.seed_roles(db)
    assert n >= 5  # OWNER/ADMIN/COMPLIANCE_OFFICER/ANALYST/... insérés

    # créer un tenant + user réels pour l'affectation (FK user_roles)
    tid = uuid.uuid4()
    uid = uuid.uuid4()
    db.execute(text(
        "INSERT INTO tenants (id, name, slug, status) VALUES (:id, 'T', :slug, 'ACTIVE')"
    ), {"id": str(tid), "slug": f"t-{str(tid)[:8]}"})
    db.execute(text(
        "INSERT INTO users (id, email, full_name, tenant_id, status, is_active) "
        "VALUES (:id, :em, 'U', :t, 'ACTIVE', true)"
    ), {"id": str(uid), "em": f"{uid}@ex.io", "t": str(tid)})
    db.commit()

    rbac_service.assign_role(db, uid, tid, "COMPLIANCE_OFFICER")
    perms = rbac_service.get_user_permissions(db, uid, tid)
    assert "alerts:manage" in perms and "sar:manage" in perms
    assert "referentiel:write" not in perms  # non accordé à ce rôle

    # ANALYST : peut évaluer le scoring mais pas gérer les alertes
    rbac_service.assign_role(db, uid, tid, "ANALYST")
    perms = rbac_service.get_user_permissions(db, uid, tid)
    assert "scoring:evaluate" in perms


@pytest.mark.integration
def test_rbac_owner_wildcard(db):
    import uuid

    from sqlalchemy import text

    from app.core.permissions import ALL
    from app.services import rbac_service
    rbac_service.seed_roles(db)
    tid = uuid.uuid4()
    uid = uuid.uuid4()
    db.execute(text("INSERT INTO tenants (id, name, slug, status) VALUES (:id,'T2',:slug,'ACTIVE')"),
               {"id": str(tid), "slug": f"t2-{str(tid)[:8]}"})
    db.execute(text(
        "INSERT INTO users (id, email, full_name, tenant_id, status, is_active) "
        "VALUES (:id,:em,'U',:t,'ACTIVE',true)"
    ), {"id": str(uid), "em": f"{uid}@ex.io", "t": str(tid)})
    db.commit()
    rbac_service.assign_role(db, uid, tid, "OWNER")
    perms = rbac_service.get_user_permissions(db, uid, tid)
    assert ALL in perms


@pytest.mark.integration
def test_ach_batch_parsing_and_ingest(db):
    from app.services import kyt_service, referentiel_service
    from app.services.integration import parse_ach_batch
    referentiel_service.seed_referentiel(db)
    batch = (
        "REF;CUSTOMER;AMOUNT;CURRENCY;COUNTERPARTY;COUNTRY;TYPE\n"
        "CHQ001;C-1001;7500;GNF;Fournisseur X;GN;CHECK\n"
        "# commentaire ignoré\n"
        "VIR002;C-2002;120000;USD;ACME Corp;US;TRANSFER\n"
    )
    entries = parse_ach_batch(batch)
    assert len(entries) == 2
    assert entries[0]["channel"].value == "CHECK"
    assert entries[1]["source_system"].value == "ACH"
    # ingestion effective
    for e in entries:
        txn, a, _ = kyt_service.ingest_transaction(db, e)
        assert txn.risk_assessment_id == a.id


@pytest.mark.integration
def test_rtgs_message_mapping(db):
    from app.services.integration import map_rtgs_message
    data = map_rtgs_message({
        "msgId": "RTGS-2026-0001",
        "debtor": {"ref": "C-1001"},
        "creditor": {"name": "Beta Bank", "country": "ir"},
        "amount": "500000", "currency": "usd", "direction": "OUT",
    })
    assert data["source_system"].value == "RTGS"
    assert data["counterparty_country"] == "IR"
    assert data["currency"] == "USD"
    assert str(data["amount"]) == "500000"


@pytest.mark.integration
def test_t24_mapping(db):
    from app.services.integration import map_t24_transaction
    rec = {
        "@id": "FT2500701",
        "TRANSACTION.TYPE": "TRANSFER",
        "DR.CR": "DEBIT",
        "AMOUNT": "25000.50",
        "CURRENCY": "EUR",
        "CUSTOMER.NO": "C-1001",
        "BENEFICIARY.COUNTRY": "IR",
    }
    data = map_t24_transaction(rec)
    assert data["currency"] == "EUR"
    assert data["counterparty_country"] == "IR"
    assert data["source_system"].value == "T24"


@pytest.mark.integration
def test_ubo_effective_ownership_through_chain(db):
    """
    Une chaîne de détention doit être aplatie par PRODUIT des pourcentages.

    Détenir 80 % d'une holding qui détient 60 % de la cible = 48 % effectifs :
    au-dessus du seuil de 25 %, donc bénéficiaire effectif — alors qu'un simple
    regard niveau par niveau ne le montrerait pas. C'est précisément le montage
    utilisé pour diluer une détention apparente.
    """
    from app.models.ubo import PartyKind
    from app.services import ubo_service

    decl = ubo_service.create_declaration(db, {
        "company_name": "Simandou Mining SA",
        "company_ref": "RCCM-GN-2026-B-001",
        "company_country": "GN",
    })

    holding = ubo_service.add_member(db, decl.id, {
        "full_name": "Guinea Holding Ltd", "kind": PartyKind.ENTITY,
        "ownership_percent": 60,
    })
    owner = ubo_service.add_member(db, decl.id, {
        "full_name": "Mamadou Diallo", "kind": PartyKind.PERSON,
        "parent_id": holding.id, "ownership_percent": 80,
    })
    petit = ubo_service.add_member(db, decl.id, {
        "full_name": "Aissatou Bah", "kind": PartyKind.PERSON,
        "parent_id": holding.id, "ownership_percent": 20,
    })

    out_owner = ubo_service.member_out(db, owner)
    out_petit = ubo_service.member_out(db, petit)

    # 80 % de 60 % = 48 % -> bénéficiaire effectif
    assert out_owner["effective_percent"] == pytest.approx(48.0)
    assert out_owner["is_beneficial_owner"] is True

    # 20 % de 60 % = 12 % -> sous le seuil, pas bénéficiaire effectif
    assert out_petit["effective_percent"] == pytest.approx(12.0)
    assert out_petit["is_beneficial_owner"] is False


@pytest.mark.integration
def test_ubo_legal_representative_is_always_beneficial_owner(db):
    """Le dirigeant est bénéficiaire effectif même sans détention de capital."""
    from app.models.ubo import PartyKind
    from app.services import ubo_service

    decl = ubo_service.create_declaration(db, {"company_name": "Conakry Trading SARL"})
    gerant = ubo_service.add_member(db, decl.id, {
        "full_name": "Ibrahima Sow", "kind": PartyKind.PERSON,
        "ownership_percent": 0, "control_nature": "LEGAL_REPRESENTATIVE",
    })
    assert ubo_service.member_out(db, gerant)["is_beneficial_owner"] is True


# ── Médias défavorables sur les personnes morales ─────────────────────────────

def _seed_adverse(db, name: str, category: str = "MONEY_LAUNDERING", active: bool = True):
    from sqlalchemy import text
    from app.services.matching import normalize_name
    db.execute(text("""
        INSERT INTO adverse_media_records
            (id, entity_name, normalized_name, category, source, summary, active)
        VALUES (gen_random_uuid(), :n, :nn,
                CAST(:c AS adverse_media_category), 'TEST', 'test', :a)
    """), {"n": name, "nn": normalize_name(name), "c": category, "a": active})
    db.commit()


@pytest.mark.integration
def test_adverse_media_rapproche_les_formes_juridiques(db):
    """« Limited » et « Ltd » désignent la même société : le rapprochement doit
    aboutir. Sans canonisation, le score tombait à 61 pour un seuil de 65."""
    from app.services import adverse_media_service as ams
    _seed_adverse(db, "Atlas Trading Ltd")

    assert ams.assess_company(db, "Atlas Trading Limited")["hit"] is True
    assert ams.assess_company(db, "ATLAS TRADING LIMITED")["hit"] is True


@pytest.mark.integration
def test_adverse_media_ne_confond_pas_deux_societes(db):
    """Une dénomination voisine ne doit pas être tenue pour la même entité."""
    from app.services import adverse_media_service as ams
    _seed_adverse(db, "Atlas Trading Ltd")

    assert ams.assess_company(db, "Boreal Trading Ltd")["hit"] is False
    assert ams.assess_company(db, "Atlas Shipping Ltd")["hit"] is False


@pytest.mark.integration
def test_adverse_media_ignore_les_signalements_desactives(db):
    from app.services import adverse_media_service as ams
    _seed_adverse(db, "Ancien Dossier SA", active=False)
    assert ams.assess_company(db, "Ancien Dossier SA")["hit"] is False


@pytest.mark.integration
def test_adverse_media_plancher_gradue_selon_la_force_du_rapprochement(db):
    """Un rapprochement seulement POSSIBLE ne porte pas le dossier en risque
    élevé : il déclenche un examen, ce qui est le bon niveau de réaction."""
    from app.services import adverse_media_service as ams
    _seed_adverse(db, "Atlas Trading Ltd", category="MONEY_LAUNDERING")

    fort = ams.assess_company(db, "Atlas Trading Limited")
    assert fort["risk_floor"] == "HIGH"          # fait grave + rapprochement fort

    faible = ams.assess_company(db, "Atlas Trading SA")
    assert faible["hit"] is True
    assert faible["risk_floor"] == "MEDIUM"      # même fait grave, mais rapprochement faible


def _make_tenant(db) -> str:
    """La base de test ne contient aucun locataire : chaque test crée le sien."""
    import uuid as _uuid
    from sqlalchemy import text
    tid = _uuid.uuid4()
    db.execute(text("RESET ROLE"))
    db.execute(text("SET ROLE auth_bypass_rls"))
    db.execute(
        text("INSERT INTO tenants (id, name, slug, status) VALUES (:t, :n, :s, 'ACTIVE')"),
        {"t": tid, "n": f"tenant-{tid.hex[:6]}", "s": f"t-{tid.hex[:8]}"},
    )
    db.commit()
    db.execute(text("RESET ROLE"))
    return str(tid)


@pytest.mark.integration
def test_adverse_media_releve_le_risque_sans_jamais_bloquer(db):
    """Effet sur la vérification d'une personne morale, mesuré en isolant le
    signalement : le même nom doit passer de LOW/PASS à un examen imposé."""
    from sqlalchemy import text
    from app.core.db import set_tenant_context
    from app.services import simple_screening_engine as eng

    tid = _make_tenant(db)
    nom = "Boreal Shipping Ltd"   # sans correspondance dans les listes de sanctions

    set_tenant_context(db, tid)
    avant = eng.run_simple_screening(db=db, name=nom, meta={"entity_type": "COMPANY"})
    assert avant["risk_level"] == "LOW" and avant["recommended_action"] == "PASS"

    # La validation opérée par _seed_adverse rend la connexion au pool et
    # efface le contexte de locataire : il faut le reposer avant de relancer.
    _seed_adverse(db, "Boreal Shipping Limited", category="CORRUPTION")

    set_tenant_context(db, tid)
    apres = eng.run_simple_screening(db=db, name=nom, meta={"entity_type": "COMPANY"})
    assert apres["risk_level"] == "MEDIUM"
    assert apres["recommended_action"] == "MANUAL_REVIEW"
    # Un signalement de presse ne bloque JAMAIS à lui seul : la base est
    # alimentée par la Conformité et un homonyme y est toujours possible.
    assert apres["recommended_action"] != "BLOCK"


@pytest.mark.integration
def test_adverse_media_ne_sapplique_pas_aux_personnes_physiques(db):
    from sqlalchemy import text
    from app.core.db import set_tenant_context
    from app.services import simple_screening_engine as eng

    tid = _make_tenant(db)
    _seed_adverse(db, "Boreal Shipping Limited", category="CORRUPTION")

    set_tenant_context(db, tid)
    r = eng.run_simple_screening(db=db, name="Boreal Shipping Ltd",
                                 meta={"entity_type": "INDIVIDUAL"})
    assert r["risk_level"] == "LOW" and r["recommended_action"] == "PASS"


# ── Recherche de presse asynchrone ────────────────────────────────────────────
#
# Seule la logique de cache est testée : l'appel à la source externe est
# volontairement hors tests, car il échoue environ deux fois sur trois et
# rendrait la suite instable.

def _press_row(db, name_norm: str, status: str, started_ago: str,
               updated_ago: str, articles: str = "null"):
    from sqlalchemy import text
    db.execute(text(f"""
        INSERT INTO press_search_cache
            (name_normalized, display_name, status, articles, started_at, updated_at)
        VALUES (:k, :k, :s, CAST(:a AS jsonb),
                now() - interval '{started_ago}', now() - interval '{updated_ago}')
        ON CONFLICT (name_normalized) DO UPDATE
           SET status = EXCLUDED.status, articles = EXCLUDED.articles,
               started_at = EXCLUDED.started_at, updated_at = EXCLUDED.updated_at
    """), {"k": name_norm, "s": status, "a": articles})
    db.commit()


@pytest.mark.integration
def test_press_jamais_cherche_est_inactif(db):
    from app.services import adverse_media_service as ams
    assert ams.press_status(db, "Societe Jamais Vue")["status"] == "IDLE"


@pytest.mark.integration
def test_press_resultat_en_cache_est_servi(db):
    from app.services import adverse_media_service as ams
    _press_row(db, "SOCIETE CACHEE", "DONE", "1 hour", "1 hour",
               '[{"title": "article"}]')
    r = ams.press_status(db, "Societe Cachee")
    assert r["status"] == "DONE" and len(r["articles"]) == 1


@pytest.mark.integration
def test_press_recherche_perdue_ne_bloque_pas_l_ecran(db):
    """Un worker redémarré en plein vol laisse une recherche « en cours » qui
    ne se terminera jamais. Sans garde-fou, l'écran tournerait sans fin."""
    from app.services import adverse_media_service as ams
    _press_row(db, "SOCIETE PERDUE", "PENDING", "20 minutes", "20 minutes")
    assert ams.press_status(db, "Societe Perdue")["status"] == "IDLE"

    # Une recherche récente, elle, doit rester signalée comme en cours.
    _press_row(db, "SOCIETE RECENTE", "PENDING", "10 seconds", "10 seconds")
    assert ams.press_status(db, "Societe Recente")["status"] == "PENDING"


@pytest.mark.integration
def test_press_resultat_perime_est_recherche_a_nouveau(db):
    from app.services import adverse_media_service as ams
    _press_row(db, "SOCIETE ANCIENNE", "DONE", "9 hours", "9 hours",
               '[{"title": "vieux"}]')
    assert ams.press_status(db, "Societe Ancienne")["status"] == "IDLE"


@pytest.mark.integration
def test_press_le_cache_est_partage_et_non_en_memoire(db):
    """La production tourne avec deux workers : le sondage peut atteindre un
    autre processus que celui qui a lancé la recherche. Le cache doit donc
    vivre en base — une session neuve doit voir le résultat."""
    from sqlalchemy import text
    from app.services import adverse_media_service as ams
    _press_row(db, "SOCIETE PARTAGEE", "DONE", "1 hour", "1 hour",
               '[{"title": "article"}]')
    n = db.execute(text(
        "SELECT COUNT(*) FROM press_search_cache WHERE name_normalized = 'SOCIETE PARTAGEE'"
    )).scalar()
    assert n == 1
    assert ams.press_status(db, "Societe Partagee")["status"] == "DONE"
