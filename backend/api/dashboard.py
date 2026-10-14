from collections import Counter, defaultdict
from datetime import timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select

from backend.attendance import session_dict
from backend.auth import PERMISSIONS, require
from backend.db import get_db, utcnow
from backend.models import AttendanceSession, AuditLog, Person
from backend.people import institution_context
from backend.reports import report_rows
from backend.schemas import Category
from backend.station import enrolled_people

router = APIRouter()
STATUS_PRIORITY = {
    "holiday": 0,
    "excused": 1,
    "on_leave": 2,
    "absent": 3,
    "pending_verification": 4,
    "present": 5,
    "late": 6,
}


@router.get("/dashboard")
def dashboard(
    request: Request,
    category: Category | None = None,
    days: int = Query(30, ge=1, le=366),
    user=Depends(require("read")),
    db=Depends(get_db),
):
    now = utcnow()
    context = institution_context(db, request.app.state.settings)
    today = now.astimezone(ZoneInfo(context["timezone"])).date()
    start = today - timedelta(days=days - 1)
    rows = report_rows(db, start, today, category=category)
    people_query = select(Person).where(Person.active.is_(True))
    if category is not None:
        people_query = people_query.where(Person.category == category)
    people = list(db.scalars(people_query))
    enrolled = set(db.scalars(enrolled_people(now)))
    population = Counter(person.category for person in people)
    daily_people = {}
    for row in rows:
        key = row["date"], row["person_id"]
        previous = daily_people.get(key)
        if previous is None or STATUS_PRIORITY[row["status"]] > STATUS_PRIORITY[previous["status"]]:
            daily_people[key] = row
    daily = defaultdict(Counter)
    departments = defaultdict(Counter)
    categories = defaultdict(Counter)
    for (day, _), row in daily_people.items():
        daily[day][row["status"]] += 1
        if day == today.isoformat():
            departments[row["department"]][row["status"]] += 1
            categories[row["category"]][row["status"]] += 1
    trend = [
        {
            "date": (start + timedelta(days=offset)).isoformat(),
            **{
                status: daily[(start + timedelta(days=offset)).isoformat()][status]
                for status in ("present", "late", "absent", "pending_verification")
            },
        }
        for offset in range(days)
    ]
    current_rows = [row for row in rows if row["date"] == today.isoformat()]
    today_counts = daily[today.isoformat()]
    sessions_query = (
        select(AttendanceSession)
        .where(
            AttendanceSession.ends_at >= now,
            AttendanceSession.finalized.is_(False),
            AttendanceSession.archived_at.is_(None),
        )
        .order_by(AttendanceSession.starts_at)
        .limit(100)
    )
    if category is not None:
        sessions_query = (
            select(AttendanceSession)
            .where(
                AttendanceSession.ends_at >= now,
                AttendanceSession.finalized.is_(False),
                AttendanceSession.archived_at.is_(None),
                AttendanceSession.category == category,
            )
            .order_by(AttendanceSession.starts_at)
            .limit(100)
        )
    sessions = [session_dict(session) for session in db.scalars(sessions_query)]
    audit_entries = []
    if "audit" in PERMISSIONS[user.role] and category is None:
        audit_entries = [
            {
                "action": entry.action,
                "created_at": entry.created_at,
                "entity": entry.entity,
                "entity_id": entry.entity_id,
            }
            for entry in db.scalars(
                select(AuditLog)
                .where(AuditLog.action.not_in(["login", "logout", "profile_photo_viewed"]))
                .order_by(AuditLog.id.desc())
                .limit(5)
            )
        ]
    return {
        **context,
        "date": today,
        "scope": category or "institution",
        "people": dict(population),
        "registered": len(people),
        "enrolled": sum(person.id in enrolled for person in people),
        "awaiting_enrollment": sum(person.id not in enrolled for person in people),
        "today": {status: today_counts[status] for status in STATUS_PRIORITY},
        "checked_in": today_counts["present"] + today_counts["late"],
        "pending_reviews": sum(row["status"] == "pending_verification" for row in current_rows),
        "trend": trend,
        "categories": [{"category": key, **dict(value)} for key, value in categories.items()],
        "departments": [{"department": key, **dict(value)} for key, value in departments.items()],
        "recent": sorted(current_rows, key=lambda row: row["check_in"] or "", reverse=True)[:8],
        "sessions": sessions,
        "administrative_activity": audit_entries,
    }
