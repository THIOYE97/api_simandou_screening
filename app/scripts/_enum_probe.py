"""Sonde en LECTURE SEULE : valeurs réelles des énumérations en production."""
from sqlalchemy import text
from app.core.db import SessionLocal
db = SessionLocal()
for t in ("record_type", "source_type", "adverse_media_category"):
    vals = [r for r in db.execute(text("""
        SELECT e.enumlabel FROM pg_enum e JOIN pg_type p ON p.oid = e.enumtypid
         WHERE p.typname = :t ORDER BY e.enumsortorder
    """), {"t": t}).scalars()]
    print(f"  {t:<24} : {vals}")
db.close()
