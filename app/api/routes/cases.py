from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text, String, cast
from app.api.deps.db import get_db_rls as get_db
from app.api.deps.auth import get_current_user


from app.schemas.cases import CaseCreate, CaseOut, CaseUpdate, CaseDetail
from app.schemas.persons import PersonUpsert, PersonOut
from app.schemas.companies import CompanyUpsert, CompanyOut, CompanyPersonCreate
from app.services import cases_service
from app.models.case import Case


# ✅ dépendance globale: tout /cases nécessite un token
router = APIRouter(
    prefix="/cases",
    tags=["cases"],
    dependencies=[Depends(get_current_user)],
)
def get_default_user_id(db: Session):
    q = text("select id from users order by created_at asc limit 1")
    uid = db.execute(q).scalar()
    if not uid:
        raise HTTPException(status_code=400, detail="No users found. Create an admin user first.")
    return uid
@router.post("", response_model=CaseOut)
def create_case(
    payload: CaseCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    created_by = user["id"]
    case = cases_service.create_case(db, payload.case_type, created_by=created_by)
    return case

@router.get("", response_model=list[CaseOut])
def list_cases(
    status: str | None = Query(default=None),
    q: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    query = db.query(Case)
    if status:
        query = query.filter(Case.status == status)

    # ✅ fix: cast(UUID -> String) proprement
    if q:
        query = query.filter(cast(Case.id, String).ilike(f"%{q}%"))

    return query.order_by(Case.created_at.desc()).all()

@router.get("/{case_id}", response_model=CaseDetail)
def get_case(case_id: UUID, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == case_id).one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    detail = {"case": case, "person": None, "company": None, "company_people": [], "documents": []}

    # person
    try:
        primary = db.execute(
            text("select entity_id from case_entities where case_id=:c and role='PRIMARY_PERSON' limit 1"),
            {"c": str(case_id)}
        ).mappings().first()

        if primary:
            row = db.execute(
                text("select * from persons where entity_id=:e"),
                {"e": str(primary["entity_id"])}
            ).mappings().first()
            if row:
                detail["person"] = dict(row)
    except Exception:
        pass

    # company + people
    try:
        primary = db.execute(
            text("select entity_id from case_entities where case_id=:c and role='PRIMARY_COMPANY' limit 1"),
            {"c": str(case_id)}
        ).mappings().first()

        if primary:
            row = db.execute(
                text("select * from companies where entity_id=:e"),
                {"e": str(primary["entity_id"])}
            ).mappings().first()
            if row:
                detail["company"] = dict(row)

            people = db.execute(text("""
                select cp.id, cp.role_type, cp.ownership_pct,
                       p.entity_id as person_entity_id, p.last_name, p.first_names
                from company_people cp
                join companies c on c.id = cp.company_id
                join persons p on p.id = cp.person_id
                where c.entity_id = :eid
                order by cp.created_at desc
            """), {"eid": str(primary["entity_id"])}).mappings().all()

            detail["company_people"] = [dict(x) for x in people]
    except Exception:
        pass

    # ✅ fix: text() obligatoire
    docs = db.execute(
        text("select * from documents where case_id=:c order by uploaded_at desc"),
        {"c": str(case_id)}
    ).mappings().all()
    detail["documents"] = [dict(d) for d in docs]

    return detail

@router.patch("/{case_id}", response_model=CaseOut)
def update_case(case_id: UUID, payload: CaseUpdate, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == case_id).one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    for k, v in payload.dict(exclude_unset=True).items():
        setattr(case, k, v)

    db.commit()
    db.refresh(case)
    return case

@router.put("/{case_id}/person", response_model=PersonOut)
def upsert_person(case_id: UUID, payload: PersonUpsert, db: Session = Depends(get_db)):
    try:
        return cases_service.upsert_person_for_case(db, case_id, payload.dict(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.put("/{case_id}/company", response_model=CompanyOut)
def upsert_company(case_id: UUID, payload: CompanyUpsert, db: Session = Depends(get_db)):
    try:
        return cases_service.upsert_company_for_case(db, case_id, payload.dict(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{case_id}/company/people")
def add_company_person(case_id: UUID, payload: CompanyPersonCreate, db: Session = Depends(get_db)):
    try:
        link = cases_service.add_company_person(
            db=db,
            case_id=case_id,
            person_entity_id=payload.person_entity_id,
            role_type=payload.role_type,
            ownership_pct=payload.ownership_pct,
        )
        return {"id": str(link.id)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))