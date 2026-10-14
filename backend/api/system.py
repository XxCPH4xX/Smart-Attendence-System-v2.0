from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select

from backend.auth import audit, require
from backend.db import get_db
from backend.models import AuditLog, Policy
from backend.people import get_policy, institution_context
from backend.schemas import InstitutionInput, PolicyInput

router = APIRouter()


@router.get("/settings")
def settings(request: Request, user=Depends(require("read")), db=Depends(get_db)):
    policy = get_policy(db)
    return {
        "policy": policy.model_dump(),
        **institution_context(db, request.app.state.settings),
        "device": request.app.state.settings.device,
        "station_staff_verification_required": not policy.station_auto_mark,
        "scheduled_staff_verification_required": True,
        "index_version": db.get(Policy, 1).index_version,
    }


@router.put("/settings")
def update_settings(data: PolicyInput, user=Depends(require("settings")), db=Depends(get_db)):
    policy = db.get(Policy, 1)
    previous = policy.values
    policy.values = data.model_dump()
    policy.index_version += 1
    audit(db, user, "settings_changed", "policy", 1, before=previous, after=policy.values)
    db.commit()
    return policy.values


@router.put("/institution")
def update_institution(
    data: InstitutionInput, request: Request, user=Depends(require("settings")), db=Depends(get_db)
):
    policy = db.get(Policy, 1)
    before = institution_context(db, request.app.state.settings)
    policy.values = {
        **get_policy(db).model_dump(),
        "institution_name": data.name,
        "institution_timezone": data.timezone,
    }
    audit(db, user, "institution_updated", "institution", 1, before=before, after=data.model_dump())
    db.commit()
    return institution_context(db, request.app.state.settings)


@router.get("/audit")
def audit_logs(
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user=Depends(require("audit")),
    db=Depends(get_db),
):
    entries = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).offset(offset).limit(limit))
    return [
        {c.name: getattr(entry, c.name) for c in AuditLog.__table__.columns} for entry in entries
    ]
