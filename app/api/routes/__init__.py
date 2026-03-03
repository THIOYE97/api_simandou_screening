from .cases import router as cases_router
from .documents import router as documents_router
from .auth import router as auth_router

routers = [auth_router, cases_router, documents_router]
