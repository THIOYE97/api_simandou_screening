# app/services/case_service.py
from __future__ import annotations

from uuid import UUID
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models.case import Case, CaseType
from app.models.person import Person
from app.models.company import Company, CompanyPerson, CompanyRoleType

# --- Constants aligned with DB enums (IMPORTANT) ---
ENTITY_TYPE_PERSON = "person"
ENTITY_TYPE_COMPANY = "company"


def _current_tenant_uuid(db: Session) -> UUID | None:
    val = db.execute(text("SELECT nullif(current_setting('app.tenant_id', true), '')")).scalar()
    if not val:
        return None
    try:
        return UUID(str(val))
    except Exception:
        return None


def _require_tenant_uuid(db: Session) -> UUID:
    tid = _current_tenant_uuid(db)
    if not tid:
        raise RuntimeError("tenant context missing (app.tenant_id is not set)")
    return tid


def _set_if_attr(obj, attr: str, value) -> None:
    try:
        if hasattr(obj, attr):
            setattr(obj, attr, value)
    except Exception:
        pass


def _create_entity(db: Session, entity_type: str, primary_name: str | None = None) -> UUID:
    """
    entities.entity_type is a Postgres enum with values: 'person', 'company'

    If entities is tenant-scoped with RLS, we must provide tenant_id.
    We do this best-effort via current_setting('app.tenant_id').
    """
    tenant_id = _current_tenant_uuid(db)

    if tenant_id:
        row = db.execute(
            text(
                """
                insert into entities (tenant_id, entity_type, primary_name, created_at, updated_at)
                values (:tenant_id, :entity_type, coalesce(:primary_name,''), now(), now())
                returning id
                """
            ),
            {"tenant_id": str(tenant_id), "entity_type": entity_type, "primary_name": primary_name or ""},
        ).fetchone()
    else:
        # fallback for non-tenant entities tables (or if RLS not enabled there)
        row = db.execute(
            text(
                """
                insert into entities (entity_type, primary_name, created_at, updated_at)
                values (:entity_type, coalesce(:primary_name,''), now(), now())
                returning id
                """
            ),
            {"entity_type": entity_type, "primary_name": primary_name or ""},
        ).fetchone()

    if not row:
        raise RuntimeError("Failed to create entity")
    return row[0]


def create_case(db: Session, case_type: CaseType, created_by: UUID) -> Case:
    """
    Create a case and attach its primary entity:
      - KYC -> PRIMARY_PERSON
      - KYB -> PRIMARY_COMPANY

    IMPORTANT: cases.created_by is NOT NULL in DB, so created_by must be provided.
    Also: cases is tenant-scoped => we set tenant_id best-effort for RLS.
    """
    if not created_by:
        raise ValueError("created_by is required (cases.created_by is NOT NULL)")

    tenant_id = _require_tenant_uuid(db)

    try:
        case = Case(case_type=case_type, created_by=created_by)
        _set_if_attr(case, "tenant_id", tenant_id)

        db.add(case)
        db.flush()  # get case.id

        if case_type == CaseType.KYC:
            entity_id = _create_entity(db, ENTITY_TYPE_PERSON, "")
            db.add(Person(entity_id=entity_id))

            # case_entities might also be tenant-scoped. We pass tenant_id if column exists.
            try:
                db.execute(
                    text(
                        """
                        insert into case_entities (tenant_id, case_id, entity_id, role, created_at)
                        values (:tenant_id, :case_id, :entity_id, 'PRIMARY_PERSON', now())
                        on conflict do nothing
                        """
                    ),
                    {"tenant_id": str(tenant_id), "case_id": str(case.id), "entity_id": str(entity_id)},
                )
            except Exception:
                # fallback if case_entities has no tenant_id column
                db.execute(
                    text(
                        """
                        insert into case_entities (case_id, entity_id, role, created_at)
                        values (:case_id, :entity_id, 'PRIMARY_PERSON', now())
                        on conflict do nothing
                        """
                    ),
                    {"case_id": str(case.id), "entity_id": str(entity_id)},
                )

        elif case_type == CaseType.KYB:
            entity_id = _create_entity(db, ENTITY_TYPE_COMPANY, "")
            db.add(Company(entity_id=entity_id))

            try:
                db.execute(
                    text(
                        """
                        insert into case_entities (tenant_id, case_id, entity_id, role, created_at)
                        values (:tenant_id, :case_id, :entity_id, 'PRIMARY_COMPANY', now())
                        on conflict do nothing
                        """
                    ),
                    {"tenant_id": str(tenant_id), "case_id": str(case.id), "entity_id": str(entity_id)},
                )
            except Exception:
                db.execute(
                    text(
                        """
                        insert into case_entities (case_id, entity_id, role, created_at)
                        values (:case_id, :entity_id, 'PRIMARY_COMPANY', now())
                        on conflict do nothing
                        """
                    ),
                    {"case_id": str(case.id), "entity_id": str(entity_id)},
                )

        else:
            raise ValueError(f"Unsupported case_type: {case_type}")

        db.commit()
        db.refresh(case)
        return case

    except IntegrityError as e:
        db.rollback()
        raise ValueError(f"DB integrity error while creating case: {str(e)}") from e
    except Exception:
        db.rollback()
        raise


def get_case_primary_entity(db: Session, case_id: UUID):
    row = db.execute(
        text(
            """
            select entity_id, role
            from case_entities
            where case_id = :case_id
            order by
              case when role in ('PRIMARY_PERSON','PRIMARY_COMPANY') then 0 else 1 end
            limit 1
            """
        ),
        {"case_id": str(case_id)},
    ).mappings().first()
    return row


def upsert_person_for_case(db: Session, case_id: UUID, data: dict) -> Person:
    primary = db.execute(
        text(
            """
            select entity_id from case_entities
            where case_id = :case_id and role = 'PRIMARY_PERSON'
            limit 1
            """
        ),
        {"case_id": str(case_id)},
    ).mappings().first()

    if not primary:
        raise ValueError("Case is not KYC or missing PRIMARY_PERSON")

    entity_id = primary["entity_id"]

    person = db.query(Person).filter(Person.entity_id == entity_id).one_or_none()
    if not person:
        person = Person(entity_id=entity_id)
        _set_if_attr(person, "tenant_id", _current_tenant_uuid(db))
        db.add(person)
        db.flush()

    for k, v in data.items():
        if hasattr(person, k):
            setattr(person, k, v)

    full_name = " ".join([data.get("last_name") or "", data.get("first_names") or ""]).strip()
    try:
        db.execute(
            text("update entities set primary_name = :n, updated_at = now() where id = :id"),
            {"n": full_name, "id": str(entity_id)},
        )
    except Exception:
        pass

    db.commit()
    db.refresh(person)
    return person


def upsert_company_for_case(db: Session, case_id: UUID, data: dict) -> Company:
    primary = db.execute(
        text(
            """
            select entity_id from case_entities
            where case_id = :case_id and role = 'PRIMARY_COMPANY'
            limit 1
            """
        ),
        {"case_id": str(case_id)},
    ).mappings().first()

    if not primary:
        raise ValueError("Case is not KYB or missing PRIMARY_COMPANY")

    entity_id = primary["entity_id"]

    company = db.query(Company).filter(Company.entity_id == entity_id).one_or_none()
    if not company:
        company = Company(entity_id=entity_id)
        _set_if_attr(company, "tenant_id", _current_tenant_uuid(db))
        db.add(company)
        db.flush()

    for k, v in data.items():
        if hasattr(company, k):
            setattr(company, k, v)

    if data.get("legal_name"):
        try:
            db.execute(
                text("update entities set primary_name = :n, updated_at = now() where id = :id"),
                {"n": data["legal_name"], "id": str(entity_id)},
            )
        except Exception:
            pass

    db.commit()
    db.refresh(company)
    return company


def add_company_person(
    db: Session,
    case_id: UUID,
    person_entity_id: UUID,
    role_type: CompanyRoleType,
    ownership_pct: Optional[float] = None,
) -> CompanyPerson:
    tenant_id = _require_tenant_uuid(db)

    # ensure case is KYB
    primary = db.execute(
        text(
            """
            select entity_id
            from case_entities
            where case_id = :case_id and role = 'PRIMARY_COMPANY'
            limit 1
            """
        ),
        {"case_id": str(case_id)},
    ).mappings().first()

    if not primary:
        raise ValueError("Case is not KYB or missing PRIMARY_COMPANY")

    company = db.query(Company).filter(Company.entity_id == primary["entity_id"]).one()

    # person row
    person = db.query(Person).filter(Person.entity_id == person_entity_id).one_or_none()
    if not person:
        person = Person(entity_id=person_entity_id)
        _set_if_attr(person, "tenant_id", tenant_id)
        db.add(person)
        db.flush()

    if role_type == CompanyRoleType.UBO and (ownership_pct is None or ownership_pct < 25.0):
        raise ValueError("UBO ownership_pct must be >= 25")

    link = CompanyPerson(
        company_id=company.id,
        person_id=person.id,
        role_type=role_type,
        ownership_pct=ownership_pct,
    )
    _set_if_attr(link, "tenant_id", tenant_id)
    db.add(link)

    # case_entities link for analyst UI
    try:
        db.execute(
            text(
                """
                insert into case_entities (tenant_id, case_id, entity_id, role, created_at)
                values (:tenant_id, :case_id, :entity_id, :role, now())
                on conflict do nothing
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "case_id": str(case_id),
                "entity_id": str(person_entity_id),
                "role": "UBO" if role_type == CompanyRoleType.UBO else "DIRECTOR",
            },
        )
    except Exception:
        db.execute(
            text(
                """
                insert into case_entities (case_id, entity_id, role, created_at)
                values (:case_id, :entity_id, :role, now())
                on conflict do nothing
                """
            ),
            {
                "case_id": str(case_id),
                "entity_id": str(person_entity_id),
                "role": "UBO" if role_type == CompanyRoleType.UBO else "DIRECTOR",
            },
        )

    db.commit()
    db.refresh(link)
    return link
