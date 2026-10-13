from datetime import date, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select

from backend.attendance_deletions import RECOVERY_DAYS, remove_records, restore_records
from backend.auth import audit, require
from backend.db import get_db, utcnow
from backend.models import AttendanceDeletion, AttendanceRecord, AttendanceSession, Person
from backend.reports import export_report, report_rows
from backend.schemas import AttendanceDeleteInput

router = APIRouter()


def filters(
    start: date,
    end: date,
    category: str | None = None,
    department_id: int | None = None,
    person_id: int | None = None,
    class_id: int | None = None,
    section: str | None = None,
    person_type: str | None = None,
    session_id: int | None = None,
):
    if end < start or (end - start).days > 366:
        raise HTTPException(422, "Choose an ordered report period of at most 366 days")
    return dict(
        start=start,
        end=end,
        category=category,
        department_id=department_id,
        person_id=person_id,
        class_id=class_id,
        section=section,
        person_type=person_type,
        session_id=session_id,
    )


@router.get("/attendance")
def records(params=Depends(filters), user=Depends(require("read")), db=Depends(get_db)):
    return report_rows(db, **params)


@router.delete("/attendance")
def reset_attendance(
    request: Request,
    params=Depends(filters),
    user=Depends(require("delete_attendance")),
    db=Depends(get_db),
):
    service = request.app.state.vision
    with service.lock:
        session_query = select(AttendanceSession).where(
            AttendanceSession.local_date.between(params["start"], params["end"])
        )
        if params["session_id"] is not None:
            session_query = session_query.where(AttendanceSession.id == params["session_id"])
        candidates = db.scalars(
            session_query.order_by(AttendanceSession.id).with_for_update()
        ).all()
        rows = report_rows(db, **params)
        sessions = {row["session_id"] for row in rows}
        if not any(
            params[key] is not None
            for key in (
                "category",
                "department_id",
                "person_id",
                "class_id",
                "section",
                "person_type",
            )
        ):
            sessions.update(session.id for session in candidates)
        if params["session_id"] is not None:
            sessions.add(params["session_id"])
        result = remove_records(
            db, user, [row["record_id"] for row in rows], "Attendance reset for selected filters"
        )
        service.stop_sessions(sessions)
    return result


@router.delete("/attendance/{record_id:int}")
def delete_record(
    record_id: int,
    data: AttendanceDeleteInput,
    request: Request,
    user=Depends(require("delete_attendance")),
    db=Depends(get_db),
):
    service = request.app.state.vision
    with service.lock:
        record = db.get(AttendanceRecord, record_id)
        sessions = {record.session_id} if record else set()
        result = remove_records(
            db, user, [record_id], "Deleted from attendance history", expected=data
        )
        service.stop_sessions(sessions)
    return result


@router.get("/attendance-deletions")
def deleted_records(user=Depends(require("delete_attendance")), db=Depends(get_db)):
    return [
        {
            "id": entry.id,
            "count": len(entry.records),
            "reason": entry.reason,
            "created_at": entry.created_at,
        }
        for entry in db.scalars(
            select(AttendanceDeletion)
            .where(
                AttendanceDeletion.restored_at.is_(None),
                AttendanceDeletion.created_at >= utcnow() - timedelta(days=RECOVERY_DAYS),
            )
            .order_by(AttendanceDeletion.created_at.desc())
            .limit(50)
        )
    ]


@router.post("/attendance-deletions/{deletion_id}/restore")
def restore_attendance(
    deletion_id: str,
    request: Request,
    user=Depends(require("delete_attendance")),
    db=Depends(get_db),
):
    with request.app.state.vision.lock:
        return restore_records(db, user, deletion_id)


@router.get("/reports/export")
def export(
    request: Request,
    kind: Literal["csv", "xlsx", "pdf"] = "csv",
    params=Depends(filters),
    user=Depends(require("export")),
    db=Depends(get_db),
):
    rows = report_rows(db, **params)
    labels = "; ".join(f"{key}: {value}" for key, value in params.items() if value is not None)
    content, media_type = export_report(rows, kind, request.app.state.settings.institution, labels)
    audit(db, user, "report_exported", "report", kind, after={"rows": len(rows), "filters": labels})
    db.commit()
    return Response(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="attendance.{kind}"'},
    )


@router.get("/overview")
def overview(request: Request, user=Depends(require("read")), db=Depends(get_db)):
    now = utcnow()
    today = now.astimezone(ZoneInfo(request.app.state.settings.timezone)).date()
    counts = dict(
        db.execute(
            select(Person.category, func.count())
            .where(Person.active.is_(True))
            .group_by(Person.category)
        ).all()
    )
    statuses = dict(
        db.execute(
            select(AttendanceRecord.status, func.count())
            .join(AttendanceSession, AttendanceRecord.session_id == AttendanceSession.id)
            .where(AttendanceSession.local_date == today)
            .group_by(AttendanceRecord.status)
        ).all()
    )
    active_sessions = db.scalar(
        select(func.count())
        .select_from(AttendanceSession)
        .where(
            AttendanceSession.starts_at <= now,
            AttendanceSession.ends_at >= now,
            AttendanceSession.finalized.is_(False),
        )
    )
    checked_in_people = db.scalar(
        select(func.count(func.distinct(AttendanceRecord.person_id)))
        .join(AttendanceSession, AttendanceRecord.session_id == AttendanceSession.id)
        .where(
            AttendanceSession.local_date == today, AttendanceRecord.status.in_(["present", "late"])
        )
    )
    return {
        "people": counts,
        "attendance": statuses,
        "checked_in_people": checked_in_people,
        "active_sessions": active_sessions,
        "date": today,
        "institution": request.app.state.settings.institution,
        "timezone": request.app.state.settings.timezone,
    }
