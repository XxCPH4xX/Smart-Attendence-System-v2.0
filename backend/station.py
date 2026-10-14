from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.auth import audit
from backend.db import utcnow
from backend.models import AttendanceSession, Consent, Enrollment, FaceTemplate, Person
from backend.people import get_policy


def enrolled_people(now):
    return (
        select(Person.id)
        .join(FaceTemplate, FaceTemplate.person_id == Person.id)
        .join(Enrollment, Enrollment.id == FaceTemplate.enrollment_id)
        .join(Consent, Consent.id == Enrollment.consent_id)
        .where(
            Person.active.is_(True),
            FaceTemplate.expires_at > now,
            Consent.revoked_at.is_(None),
            Person.is_minor.is_(False) | Consent.guardian.is_not(None),
        )
        .distinct()
    )


def daily_station(db, user, timezone, now=None):
    now = now or utcnow()
    zone = ZoneInfo(timezone)
    day = now.astimezone(zone).date()
    active_station = select(AttendanceSession).where(
        AttendanceSession.station_day == day, AttendanceSession.archived_at.is_(None)
    )
    existing = db.scalar(active_station)
    if existing:
        return existing
    start = datetime.combine(day, time.min, zone)
    end = datetime.combine(day + timedelta(days=1), time.min, zone) - timedelta(microseconds=1)
    session = AttendanceSession(
        name=f"{get_policy(db).station_name} · {day}",
        category="all",
        local_date=day,
        station_day=day,
        timezone=timezone,
        starts_at=start,
        ends_at=end,
        cutoff_at=end,
        grace_minutes=0,
        checkout_enabled=False,
        created_by=user.id,
    )
    try:
        with db.begin_nested():
            db.add(session)
            db.flush()
            audit(db, user, "station_day_opened", "session", session.id)
        db.commit()
    except IntegrityError:
        session = db.scalar(active_station)
        if session is None:
            raise
    return session
