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
from app.api.routes.sumsub import router as sumsub_router
from app.api.routes.cascade import router as cascade_router
from app.api.routes.analyst import router as analyst_router
from app.api.routes.admin_tenants import router as admin_tenants_router
from app.api.routes.auth_invite import router as auth_invite_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ✅ Précharge EasyOCR au démarrage du worker, pas au premier appel
    print("[startup] Préchargement EasyOCR...")
    try:
        from app.services.local_ocr_service import _get_reader
        _get_reader()
        print("[startup] ✅ EasyOCR prêt")
    except Exception as e:
        print(f"[startup] ⚠️ EasyOCR non disponible: {e}")
    yield


IS_DEV = os.getenv("ENVIRONMENT", "production") == "development"

app = FastAPI(
    title="simandou-screening-api",
    version="1.0.0",
    docs_url="/docs" if IS_DEV else None,      # ← None = désactivé
    redoc_url="/redoc" if IS_DEV else None,    # ← None = désactivé
    openapi_url="/openapi.json" if IS_DEV else None,  # ← cache aussi le schema
)

app.include_router(health_router)
app.include_router(screening_router)
app.include_router(admin.router)
app.include_router(auth_router)
app.include_router(cases_router)
app.include_router(documents_router)
app.include_router(sumsub_router)
app.include_router(cascade_router)
app.include_router(analyst_router)
app.include_router(admin_tenants_router)
app.include_router(auth_invite_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["app.simandou-screening.com","backoffice.simandou-screening.com"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)