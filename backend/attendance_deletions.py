from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from backend.attendance import find_record, get_session
from backend.auth import audit
from backend.db import utcnow
from backend.models import AttendanceDeletion, AttendanceEvent, AttendanceRecord, Person

RECOVERY_DAYS = 30


def remove_records(db, user, record_ids, reason, expected=None):
    records = db.scalars(select(AttendanceRecord).where(AttendanceRecord.id.in_(record_ids))).all()
    for session_id in sorted({record.session_id for record in records}):
        get_session(db, session_id)
    records = db.scalars(
        select(AttendanceRecord)
        .where(AttendanceRecord.id.in_(record_ids))
        .execution_options(populate_existing=True)
    ).all()
    if expected:
        if not records:
            raise HTTPException(404, "This attendance record was already deleted")
        record = records[0]
        if (
            record.version != expected.expected_version
            or record.updated_at != expected.expected_updated_at
        ):
            raise HTTPException(409, "This record changed. Refresh before deleting it.")
    if not records:
        return {"deleted": 0, "deletion_id": None}
    snapshots = []
    for record in records:
        values = {
            column.name: getattr(record, column.name)
            for column in AttendanceRecord.__table__.columns
        }
        values = {
            key: value.isoformat() if isinstance(value, datetime) else value
            for key, value in values.items()
        }
        values["events"] = [
            {
                "event_key": event.event_key,
                "actor_id": event.actor_id,
                "action": event.action,
                "reason": event.reason,
                "created_at": event.created_at.isoformat(),
            }
            for event in db.scalars(
                select(AttendanceEvent).where(AttendanceEvent.record_id == record.id)
            )
        ]
        snapshots.append(values)
    deletion = AttendanceDeletion(
        id=str(uuid4()), actor_id=user.id, records=snapshots, reason=reason
    )
    db.add(deletion)
    for record in records:
        db.delete(record)
    audit(
        db,
        user,
        "attendance_deleted",
        "attendance_deletion",
        deletion.id,
        after={"count": len(records), "record_ids": record_ids},
        reason=reason,
    )
    db.commit()
    return {"deleted": len(records), "deletion_id": deletion.id}


def restore_records(db, user, deletion_id):
    deletion = db.scalar(
        select(AttendanceDeletion).where(AttendanceDeletion.id == deletion_id).with_for_update()
    )
    if not deletion or deletion.created_at < utcnow() - timedelta(days=RECOVERY_DAYS):
        raise HTTPException(404, "These records are no longer available for recovery")
    if deletion.restored_at:
        raise HTTPException(409, "These records have already been restored")
    for session_id in sorted({row["session_id"] for row in deletion.records}):
        get_session(db, session_id)
    for row in deletion.records:
        if not db.get(Person, row["person_id"]):
            raise HTTPException(
                409, "A person in this group no longer exists; these records cannot be restored"
            )
        if find_record(db, row["session_id"], row["person_id"]):
            raise HTTPException(
                409, "New attendance exists for a person in this group. No records were restored."
            )
    for row in deletion.records:
        values = {
            key: value
            for key, value in row.items()
            if key not in {"id", "events", "version", "updated_at"}
        }
        for key in ("check_in", "check_out", "created_at"):
            values[key] = datetime.fromisoformat(values[key]) if values[key] else None
        record = AttendanceRecord(**values)
        db.add(record)
        db.flush()
        for event in row["events"]:
            db.add(
                AttendanceEvent(
                    record_id=record.id,
                    **{
                        **event,
                        "event_key": str(uuid4()),
                        "created_at": datetime.fromisoformat(event["created_at"]),
                    },
                )
            )
    deletion.restored_at = utcnow()
    audit(
        db,
        user,
        "attendance_restored",
        "attendance_deletion",
        deletion.id,
        after={"count": len(deletion.records)},
    )
    db.commit()
    return {"restored": len(deletion.records)}
