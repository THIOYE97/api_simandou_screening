from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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


app = FastAPI(title="simandou-screening-api", version="1.0.0")

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
    allow_origins=[
        "https://simandou-screening-frontend.vercel.app",
        "https://back-office-simandou-screening.vercel.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)