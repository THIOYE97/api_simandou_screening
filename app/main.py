# app/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import get_logger, setup_logging
from app.core.observability import RequestContextMiddleware, init_sentry

# --- Logging setup (avant import des routes pour capturer leurs logs) ---
setup_logging(level=settings.LOG_LEVEL, json_output=settings.LOG_JSON)
logger = get_logger("simandou.main")

# --- Sentry (no-op si SENTRY_DSN absent) ---
init_sentry()

# --- Routers (import après setup_logging) ---
from app.api.routes import admin  # noqa: E402
from app.api.routes.admin_tenants import router as admin_tenants_router  # noqa: E402
from app.api.routes.adverse_media import router as adverse_media_router  # noqa: E402
from app.api.routes.blacklist import router as blacklist_router  # noqa: E402
from app.api.routes.alerting import router as alerting_router  # noqa: E402
from app.api.routes.analyst import router as analyst_router  # noqa: E402
from app.api.routes.auth import router as auth_router  # noqa: E402
from app.api.routes.cascade import router as cascade_router  # noqa: E402
from app.api.routes.cases import router as cases_router  # noqa: E402
from app.api.routes.documents import router as documents_router  # noqa: E402
from app.api.routes.health import router as health_router  # noqa: E402
from app.api.routes.integration import router as integration_router  # noqa: E402
from app.api.routes.kyt import router as kyt_router  # noqa: E402
from app.api.routes.ubo import router as ubo_router  # noqa: E402
from app.api.routes.offshore import router as offshore_router  # noqa: E402
from app.api.routes.rbac import router as rbac_router  # noqa: E402
from app.api.routes.referentiel import router as referentiel_router  # noqa: E402
from app.api.routes.reporting import router as reporting_router  # noqa: E402
from app.api.routes.scoring import router as scoring_router  # noqa: E402
from app.api.routes.screening import router as screening_router  # noqa: E402
from app.api.routes.security import router as security_router  # noqa: E402
from app.api.routes.settings_routes import router as settings_router  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "startup",
        extra={
            "env": settings.ENVIRONMENT,
            "log_level": settings.LOG_LEVEL,
            "rate_limit_enabled": settings.RATE_LIMIT_ENABLED,
            "storage_backend": settings.STORAGE_BACKEND,
            "anthropic_ready": bool(settings.ANTHROPIC_API_KEY),
        },
    )
    yield
    logger.info("shutdown")


app = FastAPI(
    title="simandou-screening-api",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.is_dev else None,
    redoc_url="/redoc" if settings.is_dev else None,
    openapi_url="/openapi.json" if settings.is_dev else None,
)

# --- Rate limiter ---
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request, exc: RateLimitExceeded):
    logger.warning(
        "rate_limit_exceeded",
        extra={"path": request.url.path, "detail": str(exc.detail)},
    )
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please slow down."},
        headers={"Retry-After": "60"},
    )


# --- Request ID / access log middleware (avant CORS pour couvrir preflights) ---
app.add_middleware(RequestContextMiddleware)

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["x-request-id"],
)

# --- Routers ---
app.include_router(health_router)
app.include_router(screening_router)
app.include_router(admin.router)
app.include_router(auth_router)
app.include_router(cases_router)
app.include_router(documents_router)
app.include_router(cascade_router)
app.include_router(analyst_router)
app.include_router(admin_tenants_router)
app.include_router(settings_router)
app.include_router(referentiel_router)
app.include_router(scoring_router)
app.include_router(alerting_router)
app.include_router(kyt_router)
app.include_router(ubo_router)
app.include_router(offshore_router)
app.include_router(reporting_router)
app.include_router(integration_router)
app.include_router(rbac_router)
app.include_router(adverse_media_router)
app.include_router(blacklist_router)
app.include_router(security_router)
