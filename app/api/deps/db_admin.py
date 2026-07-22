from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.api.deps.db import get_db_rls

def get_db_admin(
    db: Session = Depends(get_db_rls),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    user=Depends(lambda: None),  # sera remplacé via Depends(get_current_user) dans routes
):
    # NOTE: ce dep est utile surtout si tu veux le mettre après get_current_user dans les routes.
    return db
