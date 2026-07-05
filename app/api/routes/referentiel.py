"""
Module 1 — Référentiel : endpoints REST.

Gestion du référentiel unique (pays/GAFI, secteurs, catégories de clients,
scénarios de risque paramétrables). Lecture = `referentiel:read` implicite
(token requis) ; modification = permission `referentiel:write`.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db_rls as get_db
from app.api.deps.rbac import require
from app.schemas.referentiel import (
    ClientCategoryIn,
    ClientCategoryOut,
    CountryIn,
    CountryOut,
    CountryUpdate,
    CurrencyIn,
    CurrencyOut,
    CurrencyUpdate,
    ScenarioIn,
    ScenarioOut,
    ScenarioUpdate,
    SectorIn,
    SectorOut,
)
from app.services import referentiel_service as svc

router = APIRouter(
    prefix="/referentiel",
    tags=["referentiel"],
    dependencies=[Depends(get_current_user)],
)

_WRITE = [Depends(require("referentiel:write"))]


# --- Pays -----------------------------------------------------------------
@router.get("/countries", response_model=list[CountryOut])
def list_countries(active_only: bool = False, db=Depends(get_db)):
    return svc.list_countries(db, active_only=active_only)


@router.post("/countries", response_model=CountryOut, dependencies=_WRITE)
def create_country(payload: CountryIn, db=Depends(get_db)):
    return svc.create_country(db, payload.model_dump())


@router.patch("/countries/{country_id}", response_model=CountryOut, dependencies=_WRITE)
def update_country(country_id: UUID, payload: CountryUpdate, db=Depends(get_db)):
    obj = svc.update_country(db, country_id, payload.model_dump(exclude_unset=True))
    if not obj:
        raise HTTPException(status_code=404, detail="Country not found")
    return obj


# --- Secteurs -------------------------------------------------------------
@router.get("/sectors", response_model=list[SectorOut])
def list_sectors(db=Depends(get_db)):
    return svc.list_sectors(db)


@router.post("/sectors", response_model=SectorOut, dependencies=_WRITE)
def create_sector(payload: SectorIn, db=Depends(get_db)):
    return svc.create_sector(db, payload.model_dump())


# --- Catégories de clients ------------------------------------------------
@router.get("/client-categories", response_model=list[ClientCategoryOut])
def list_client_categories(db=Depends(get_db)):
    return svc.list_client_categories(db)


@router.post("/client-categories", response_model=ClientCategoryOut, dependencies=_WRITE)
def create_client_category(payload: ClientCategoryIn, db=Depends(get_db)):
    return svc.create_client_category(db, payload.model_dump())


# --- Devises ---------------------------------------------------------------
@router.get("/currencies", response_model=list[CurrencyOut])
def list_currencies(active_only: bool = False, db=Depends(get_db)):
    return svc.list_currencies(db, active_only=active_only)


@router.post("/currencies", response_model=CurrencyOut, dependencies=_WRITE)
def create_currency(payload: CurrencyIn, db=Depends(get_db)):
    return svc.create_currency(db, payload.model_dump())


@router.patch("/currencies/{currency_id}", response_model=CurrencyOut, dependencies=_WRITE)
def update_currency(currency_id: UUID, payload: CurrencyUpdate, db=Depends(get_db)):
    obj = svc.update_currency(db, currency_id, payload.model_dump(exclude_unset=True))
    if not obj:
        raise HTTPException(status_code=404, detail="Currency not found")
    return obj


# --- Scénarios de risque (paramétrables) ----------------------------------
@router.get("/scenarios", response_model=list[ScenarioOut])
def list_scenarios(active_only: bool = False, db=Depends(get_db)):
    return svc.list_scenarios(db, active_only=active_only)


@router.post("/scenarios", response_model=ScenarioOut, dependencies=_WRITE)
def create_scenario(payload: ScenarioIn, db=Depends(get_db)):
    return svc.create_scenario(db, payload.model_dump())


@router.patch("/scenarios/{scenario_id}", response_model=ScenarioOut, dependencies=_WRITE)
def update_scenario(scenario_id: UUID, payload: ScenarioUpdate, db=Depends(get_db)):
    obj = svc.update_scenario(db, scenario_id, payload.model_dump(exclude_unset=True))
    if not obj:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return obj


# --- Seed (initialisation des données de référence) -----------------------
@router.post("/seed", dependencies=_WRITE)
def seed(db=Depends(get_db)):
    created = svc.seed_referentiel(db)
    return {"status": "ok", "created": created}
