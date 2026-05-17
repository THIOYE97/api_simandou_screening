# app/models/__init__.py
from __future__ import annotations

import pkgutil
import importlib

from app.models.base import Base  # noqa: F401
from app.models.users import User
from app.models.tenant import Tenant
from app.models.user_role import UserRole
from app.models.tenant_invitation import TenantInvitation
from app.models.document import Document
from app.models.refresh_token import RefreshToken

def load_all_models() -> None:
    package_name = __name__
    package = importlib.import_module(package_name)

    for _, module_name, is_pkg in pkgutil.iter_modules(package.__path__):
        if is_pkg:
            continue
        if module_name in {"__init__", "base"}:
            continue
        importlib.import_module(f"{package_name}.{module_name}")

__all__ = ["User", "Tenant", "UserRole", "TenantInvitation", "Document", "RefreshToken"]
