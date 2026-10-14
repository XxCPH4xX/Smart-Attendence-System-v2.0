from datetime import date
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select

from backend import attendance
from backend.api.common import lookup
from backend.auth import audit, require
from backend.db import get_db, utcnow
from backend.models import (
    AttendanceRecord,
    AttendanceSession,
    Catalog,
    Holiday,
    Leave,
    Person,
    SessionMember,
)
from backend.people import get_policy
from backend.schemas import (
    CatalogInput,
    Category,
    CorrectionInput,
    HolidayInput,
    LeaveInput,
    ReasonInput,
    SessionInput,
)

router = APIRouter()


@router.get("/catalog")
def catalog(user=Depends(require("read")), db=Depends(get_db)):
    return [
        {"id": c.id, "kind": c.kind, "name": c.name, "details": c.details}
        for c in db.scalars(select(Catalog).order_by(Catalog.kind, Catalog.name))
    ]


@router.post("/catalog", status_code=201)
def add_catalog(data: CatalogInput, user=Depends(require("schedule")), db=Depends(get_db)):
    entry = Catalog(**data.model_dump())
    db.add(entry)
    db.flush()
    audit(db, user, "catalog_created", "catalog", entry.id, after=data.model_dump())
    db.commit()
    return {"id": entry.id}


@router.put("/catalog/{entry_id}")
def update_catalog(
    entry_id: int, data: CatalogInput, user=Depends(require("schedule")), db=Depends(get_db)
):
    entry = lookup(db, Catalog, entry_id)
    if data.kind != entry.kind:
        raise HTTPException(409, "Catalog type cannot change")
    entry.name, entry.details = data.name, data.details
    audit(db, user, "catalog_updated", "catalog", entry.id, after=data.model_dump())
    db.commit()
    return {"id": entry.id}


@router.get("/sessions")
def sessions(
    category: Category | None = None,
    archived: bool = False,
    user=Depends(require("read")),
    db=Depends(get_db),
):
    query = select(AttendanceSession)
    query = query.where(
        AttendanceSession.archived_at.is_not(None)
        if archived
        else AttendanceSession.archived_at.is_(None)
    )
    if category is not None:
        query = query.where(AttendanceSession.category == category)
    entries = list(db.scalars(query.order_by(AttendanceSession.starts_at.desc()).limit(500)))
    counts = dict(
        db.execute(
            select(AttendanceRecord.session_id, func.count())
            .where(AttendanceRecord.session_id.in_([entry.id for entry in entries]))
            .group_by(AttendanceRecord.session_id)
        ).all()
    )
    return [
        {**attendance.session_dict(entry), "record_count": counts.get(entry.id, 0)}
        for entry in entries
    ]


@router.delete("/sessions/{session_id}")
def remove_session(
    session_id: int, request: Request, user=Depends(require("schedule")), db=Depends(get_db)
):
    service = request.app.state.vision
    with service.lock:
        session = attendance.get_session(db, session_id)
        if not session.archived_at:
            before = attendance.session_dict(session)
            session.archived_at = utcnow()
            audit(
                db,
                user,
                "session_removed",
                "session",
                session.id,
                before=before,
            )
            db.commit()
        service.stop_sessions({session.id})
    return {"removed": True}


@router.post("/sessions/{session_id}/restore")
def restore_session(
    session_id: int, request: Request, user=Depends(require("schedule")), db=Depends(get_db)
):
    with request.app.state.vision.lock:
        session = attendance.get_session(db, session_id)
        if session.archived_at:
            if session.station_day is not None and db.scalar(
                select(AttendanceSession.id).where(
                    AttendanceSession.station_day == session.station_day,
                    AttendanceSession.archived_at.is_(None),
                )
            ):
                raise HTTPException(
                    409,
                    "A daily station already exists for this date. Its removed session's records remain in Reports.",
                )
            session.archived_at = None
            audit(db, user, "session_restored", "session", session.id)
            db.commit()
    return attendance.session_dict(session)


@router.get("/sessions/{session_id}/roster")
def roster(
    session_id: int,
    category: Category | None = None,
    user=Depends(require("read")),
    db=Depends(get_db),
):
    session = lookup(db, AttendanceSession, session_id)
    if category is not None and session.station_day is None and session.category != category:
        raise HTTPException(404, "Session not found in this category")
    if session.station_day is not None:
        query = select(Person.id).where(Person.active.is_(True))
        if category is not None:
            query = query.where(Person.category == category)
        return list(db.scalars(query))
    return list(
        db.scalars(select(SessionMember.person_id).where(SessionMember.session_id == session_id))
    )


@router.post("/sessions", status_code=201)
def add_session(data: SessionInput, user=Depends(require("schedule")), db=Depends(get_db)):
    local_date = data.starts_at.astimezone(ZoneInfo(data.timezone)).date()
    if local_date.weekday() not in get_policy(db).working_days and not db.get(Holiday, local_date):
        raise HTTPException(
            422, "Session is outside institution working days; update system settings"
        )
    members = db.scalars(
        select(Person).where(
            Person.id.in_(data.person_ids),
            Person.active.is_(True),
            Person.category == data.category,
        )
    ).all()
    if len(members) != len(data.person_ids):
        raise HTTPException(422, "Every roster member must be active and in the selected category")
    session = AttendanceSession(
        **data.model_dump(exclude={"person_ids"}), local_date=local_date, created_by=user.id
    )
    db.add(session)
    db.flush()
    db.add_all([SessionMember(session_id=session.id, person_id=p.id) for p in members])
    audit(
        db,
        user,
        "session_created",
        "session",
        session.id,
        after={"members": data.person_ids, "name": session.name},
    )
    db.commit()
    return attendance.session_dict(session)


@router.post("/sessions/{session_id}/finalize")
def close_session(session_id: int, user=Depends(require("schedule")), db=Depends(get_db)):
    return {"records_added": attendance.finalize(db, user, session_id)}


@router.get("/holidays")
def holidays(user=Depends(require("read")), db=Depends(get_db)):
    return [
        {"day": h.day, "name": h.name} for h in db.scalars(select(Holiday).order_by(Holiday.day))
    ]


@router.post("/holidays")
def set_holiday(data: HolidayInput, user=Depends(require("schedule")), db=Depends(get_db)):
    entry = db.get(Holiday, data.day) or Holiday(day=data.day)
    entry.name = data.name
    db.add(entry)
    audit(db, user, "holiday_saved", "holiday", data.day, after=data.model_dump(mode="json"))
    db.commit()
    return {"day": data.day}


@router.delete("/holidays/{day}", status_code=204)
def remove_holiday(day: date, user=Depends(require("schedule")), db=Depends(get_db)):
    db.delete(lookup(db, Holiday, day))
    audit(db, user, "holiday_removed", "holiday", day)
    db.commit()


@router.get("/leaves")
def leaves(
    category: Category | None = None,
    person_id: int | None = None,
    user=Depends(require("read")),
    db=Depends(get_db),
):
    query = select(Leave).join(Person, Person.id == Leave.person_id)
    if category is not None:
        query = query.where(Person.category == category)
    if person_id is not None:
        query = query.where(Person.id == person_id)
    return [
        {
            "id": leave.id,
            "person_id": leave.person_id,
            "starts_on": leave.starts_on,
            "ends_on": leave.ends_on,
            "reason": leave.reason,
        }
        for leave in db.scalars(query.order_by(Leave.starts_on.desc()).limit(500))
    ]


@router.post("/leaves", status_code=201)
def add_leave(data: LeaveInput, user=Depends(require("schedule")), db=Depends(get_db)):
    lookup(db, Person, data.person_id)
    entry = Leave(**data.model_dump(), approved_by=user.id)
    db.add(entry)
    db.flush()
    audit(db, user, "leave_approved", "leave", entry.id, after=data.model_dump(mode="json"))
    db.commit()
    return {"id": entry.id}


@router.delete("/leaves/{leave_id}", status_code=204)
def remove_leave(
    leave_id: int, data: ReasonInput, user=Depends(require("schedule")), db=Depends(get_db)
):
    db.delete(lookup(db, Leave, leave_id))
    audit(db, user, "leave_revoked", "leave", leave_id, reason=data.reason)
    db.commit()


@router.post("/attendance/correct")
def correction(data: CorrectionInput, user=Depends(require("correct")), db=Depends(get_db)):
    record = attendance.correct(db, user, data)
    return {"id": record.id, **attendance.record_snapshot(record)}


@router.post("/attendance/{record_id}/approve")
def approve(
    record_id: int, data: ReasonInput, user=Depends(require("correct")), db=Depends(get_db)
):
    record = attendance.approve(db, user, record_id, data.reason)
    return {"id": record.id, **attendance.record_snapshot(record)}
