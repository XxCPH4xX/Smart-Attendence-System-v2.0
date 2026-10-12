from datetime import date
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select

from backend.auth import (
    audit,
    require,
)
from backend.db import get_db, utcnow
from backend.models import (
    AttendanceRecord,
    AttendanceSession,
    Person,
)
from backend.reports import export_report, report_rows

router = APIRouter()


def filters(
    start: date,
    end: date,
    category: str | None = None,
    department_id: int | None = None,
    person_id: int | None = None,
    class_id: int | None = None,
    section: str | None = None,
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
    )


@router.get("/attendance")
def records(params=Depends(filters), user=Depends(require("read")), db=Depends(get_db)):
    return report_rows(db, **params)


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
    counts = dict(db.execute(select(Person.category, func.count()).group_by(Person.category)).all())
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
    return {
        "people": counts,
        "attendance": statuses,
        "active_sessions": active_sessions,
        "date": today,
        "institution": request.app.state.settings.institution,
        "timezone": request.app.state.settings.timezone,
    }
