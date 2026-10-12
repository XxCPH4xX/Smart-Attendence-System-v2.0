from datetime import timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select

from backend.auth import audit
from backend.db import utcnow
from backend.models import (
    AttendanceEvent,
    AttendanceRecord,
    AttendanceSession,
    Holiday,
    Leave,
    Person,
    SessionMember,
)


def record_snapshot(record):
    if not record:
        return None
    return {
        "status": record.status,
        "source": record.source,
        "verification": record.verification,
        "check_in": record.check_in.isoformat() if record.check_in else None,
        "check_out": record.check_out.isoformat() if record.check_out else None,
        "version": record.version,
    }


def get_session(db, session_id):
    # Row locks serialize decisions on PostgreSQL; SQLite uniqueness and busy timeout
    # provide the corresponding final guard when concurrent frames arrive.
    session = db.scalar(
        select(AttendanceSession).where(AttendanceSession.id == session_id).with_for_update()
    )
    if not session:
        raise HTTPException(404, "Attendance session not found")
    return session


def membership(db, session, person_id):
    person = db.get(Person, person_id)
    if not person or not person.active:
        raise HTTPException(409, "Person is inactive or unavailable")
    if not db.get(SessionMember, (session.id, person_id)):
        raise HTTPException(409, "Person is not in this session's roster")
    return person


def find_record(db, session_id, person_id):
    return db.scalar(
        select(AttendanceRecord).where(
            AttendanceRecord.session_id == session_id, AttendanceRecord.person_id == person_id
        )
    )


def exception_status(db, session, person_id):
    if db.get(Holiday, session.local_date):
        return "holiday"
    leave = db.scalar(
        select(Leave.id).where(
            Leave.person_id == person_id,
            Leave.starts_on <= session.local_date,
            Leave.ends_on >= session.local_date,
        )
    )
    return "on_leave" if leave else None


def recognized_checkin(db, user, session_id, person_id, event_key, now=None):
    """Only server-side, temporally stable vision results call this entry point."""
    now = now or utcnow()
    session = get_session(db, session_id)
    membership(db, session, person_id)
    existing = find_record(db, session_id, person_id)
    if existing:
        return existing, "Already checked in" if existing.check_in else "Existing attendance record"
    if session.finalized or not session.starts_at <= now <= session.cutoff_at:
        raise HTTPException(409, "Outside the open check-in window")
    exception = exception_status(db, session, person_id)
    if exception:
        raise HTTPException(409, f"Attendance is covered by {exception.replace('_', ' ')}")
    # Camera recognition cannot establish liveness. A human must approve each record.
    record = AttendanceRecord(
        session_id=session_id,
        person_id=person_id,
        status="pending_verification",
        source="face",
        verification="pending",
        check_in=now,
    )
    db.add(record)
    db.flush()
    db.add(
        AttendanceEvent(
            event_key=event_key, record_id=record.id, actor_id=user.id, action="recognition_pending"
        )
    )
    audit(
        db, user, "attendance_recognition", "attendance", record.id, after=record_snapshot(record)
    )
    db.commit()
    return record, "Recorded; staff verification required"


def correct(db, user, data):
    session = get_session(db, data.session_id)
    membership(db, session, data.person_id)
    for timestamp in (data.check_in, data.check_out):
        if timestamp and not session.starts_at <= timestamp <= session.ends_at:
            raise HTTPException(422, "Attendance times must lie within the session")
    if data.check_out and not session.checkout_enabled:
        raise HTTPException(409, "Checkout is disabled for this session")
    record = find_record(db, session.id, data.person_id)
    if (record.version if record else 0) != data.expected_version:
        raise HTTPException(409, "Record changed. Refresh before correcting it.")
    before = record_snapshot(record)
    if not record:
        record = AttendanceRecord(session_id=session.id, person_id=data.person_id)
        db.add(record)
    record.status = data.status.value
    record.check_in = data.check_in
    record.check_out = data.check_out
    record.source = "manual" if not before else "corrected"
    record.verification = "pending" if data.status == "pending_verification" else "staff_verified"
    db.flush()
    db.add(
        AttendanceEvent(
            event_key=str(uuid4()),
            record_id=record.id,
            actor_id=user.id,
            action="correction",
            reason=data.reason,
        )
    )
    audit(
        db,
        user,
        "attendance_corrected",
        "attendance",
        record.id,
        before=before,
        after=record_snapshot(record),
        reason=data.reason,
    )
    db.commit()
    return record


def approve(db, user, record_id, reason):
    record = db.get(AttendanceRecord, record_id)
    if not record:
        raise HTTPException(404, "Attendance record not found")
    session = get_session(db, record.session_id)
    membership(db, session, record.person_id)
    if record.verification != "pending" or not record.check_in:
        raise HTTPException(409, "Only pending check-ins can be approved")
    before = record_snapshot(record)
    record.status = (
        "late"
        if record.check_in > session.starts_at + timedelta(minutes=session.grace_minutes)
        else "present"
    )
    record.verification = "staff_verified"
    db.flush()
    db.add(
        AttendanceEvent(
            event_key=str(uuid4()),
            record_id=record.id,
            actor_id=user.id,
            action="verified",
            reason=reason,
        )
    )
    audit(
        db,
        user,
        "attendance_verified",
        "attendance",
        record.id,
        before=before,
        after=record_snapshot(record),
        reason=reason,
    )
    db.commit()
    return record


def finalize(db, user, session_id, now=None):
    now = now or utcnow()
    session = get_session(db, session_id)
    if now <= session.ends_at:
        raise HTTPException(409, "Session must end before absences can be finalized")
    if session.finalized:
        return 0
    roster = db.scalars(
        select(SessionMember.person_id).where(SessionMember.session_id == session.id)
    ).all()
    count = 0
    for person_id in roster:
        if find_record(db, session.id, person_id):
            continue
        person = db.get(Person, person_id)
        if not person.active:
            continue
        status = exception_status(db, session, person_id) or "absent"
        record = AttendanceRecord(
            session_id=session.id,
            person_id=person_id,
            status=status,
            source="schedule",
            verification="schedule",
        )
        db.add(record)
        db.flush()
        db.add(
            AttendanceEvent(
                event_key=f"finalize:{session.id}:{person_id}",
                record_id=record.id,
                actor_id=user.id,
                action="finalized",
            )
        )
        count += 1
    session.finalized = True
    audit(db, user, "session_finalized", "session", session.id, after={"records_added": count})
    db.commit()
    return count


def session_dict(session):
    zone = ZoneInfo(session.timezone)
    return {
        "id": session.id,
        "name": session.name,
        "category": session.category,
        "local_date": session.local_date.isoformat(),
        "timezone": session.timezone,
        "starts_at": session.starts_at.astimezone(zone).isoformat(),
        "ends_at": session.ends_at.astimezone(zone).isoformat(),
        "cutoff_at": session.cutoff_at.astimezone(zone).isoformat(),
        "grace_minutes": session.grace_minutes,
        "checkout_enabled": session.checkout_enabled,
        "finalized": session.finalized,
    }
