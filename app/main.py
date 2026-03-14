# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os

from app.api.routes.screening import router as screening_router
from app.api.routes.health import router as health_router
from app.api.routes import admin
from app.api.routes.cases import router as cases_router
from app.api.routes.documents import router as documents_router
from app.api.routes.auth import router as auth_router
from app.api.routes.cascade import router as cascade_router
from app.api.routes.analyst import router as analyst_router
from app.api.routes.admin_tenants import router as admin_tenants_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Claude Vision API — pas de preload RAM nécessaire, juste vérifier la clé
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        print("[startup] ✅ ANTHROPIC_API_KEY présente — Claude Vision OCR prêt")
    else:
        print("[startup] ⚠️  ANTHROPIC_API_KEY manquante — OCR échouera")
    yield


IS_DEV = os.getenv("ENVIRONMENT", "production") == "development"

app = FastAPI(
    title="simandou-screening-api",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if IS_DEV else None,
    redoc_url="/redoc" if IS_DEV else None,
    openapi_url="/openapi.json" if IS_DEV else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://app.simandou-screening.com",
        "https://backoffice.simandou-screening.com"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(screening_router)
app.include_router(admin.router)
app.include_router(auth_router)
app.include_router(cases_router)
app.include_router(documents_router)
app.include_router(cascade_router)
app.include_router(analyst_router)
app.include_router(admin_tenants_router)
