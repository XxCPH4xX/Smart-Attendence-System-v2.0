from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base, UTCDateTime, utcnow


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(30))
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    bucket: Mapped[str] = mapped_column(String(64), index=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class Catalog(Base):
    __tablename__ = "catalog"
    __table_args__ = (UniqueConstraint("kind", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(120))
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class Person(Base):
    __tablename__ = "people"
    id: Mapped[int] = mapped_column(primary_key=True)
    institutional_id: Mapped[str] = mapped_column(String(80), unique=True)
    full_name: Mapped[str] = mapped_column(String(160), index=True)
    category: Mapped[str] = mapped_column(String(20), index=True)
    custom_type: Mapped[str | None] = mapped_column(String(80))
    age: Mapped[int | None]
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(40))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("catalog.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    joined_on: Mapped[date] = mapped_column(Date)
    notes: Mapped[str] = mapped_column(Text, default="")
    is_minor: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class PersonDetails(Base):
    __tablename__ = "person_details"
    person_id: Mapped[int] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE"), primary_key=True
    )
    student_id: Mapped[str | None] = mapped_column(String(80))
    employee_id: Mapped[str | None] = mapped_column(String(80))
    class_id: Mapped[int | None] = mapped_column(ForeignKey("catalog.id"))
    section: Mapped[str | None] = mapped_column(String(80))
    academic_year: Mapped[str | None] = mapped_column(String(40))
    semester: Mapped[str | None] = mapped_column(String(40))
    roll_number: Mapped[str | None] = mapped_column(String(80))
    designation: Mapped[str | None] = mapped_column(String(120))
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("catalog.id"))
    assigned_courses: Mapped[list] = mapped_column(JSON, default=list)


class Consent(Base):
    __tablename__ = "consents"
    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    basis: Mapped[str] = mapped_column(String(40))
    statement: Mapped[str] = mapped_column(Text)
    guardian: Mapped[str | None] = mapped_column(String(160))
    recorded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Enrollment(Base):
    __tablename__ = "enrollments"
    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    consent_id: Mapped[int] = mapped_column(ForeignKey("consents.id"))
    recorded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    sample_count: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class FaceTemplate(Base):
    __tablename__ = "face_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), index=True)
    enrollment_id: Mapped[int] = mapped_column(ForeignKey("enrollments.id", ondelete="CASCADE"))
    encrypted_vector: Mapped[bytes] = mapped_column(LargeBinary)
    model_version: Mapped[str] = mapped_column(String(80))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


class ProfilePhoto(Base):
    __tablename__ = "profile_photos"
    person_id: Mapped[int] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE"), primary_key=True
    )
    encrypted_jpeg: Mapped[bytes] = mapped_column(LargeBinary)


class Policy(Base):
    __tablename__ = "policies"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    values: Mapped[dict] = mapped_column(JSON, default=dict)
    index_version: Mapped[int] = mapped_column(default=0)


class AttendanceSession(Base):
    __tablename__ = "attendance_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(20))
    local_date: Mapped[date] = mapped_column(Date, index=True)
    station_day: Mapped[date | None] = mapped_column(Date)
    timezone: Mapped[str] = mapped_column(String(80))
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime)
    cutoff_at: Mapped[datetime] = mapped_column(UTCDateTime)
    grace_minutes: Mapped[int] = mapped_column(default=10)
    checkout_enabled: Mapped[bool] = mapped_column(default=False)
    finalized: Mapped[bool] = mapped_column(default=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))


class SessionMember(Base):
    __tablename__ = "session_members"
    session_id: Mapped[int] = mapped_column(
        ForeignKey("attendance_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"), primary_key=True)


class Holiday(Base):
    __tablename__ = "holidays"
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    name: Mapped[str] = mapped_column(String(160))


class Leave(Base):
    __tablename__ = "leave_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"), index=True)
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(Text)
    approved_by: Mapped[int] = mapped_column(ForeignKey("users.id"))


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (UniqueConstraint("session_id", "person_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("attendance_sessions.id"), index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"), index=True)
    status: Mapped[str] = mapped_column(String(30))
    source: Mapped[str] = mapped_column(String(30))
    verification: Mapped[str] = mapped_column(String(30))
    check_in: Mapped[datetime | None] = mapped_column(UTCDateTime)
    check_out: Mapped[datetime | None] = mapped_column(UTCDateTime)
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    __mapper_args__ = {"version_id_col": version}


class AttendanceEvent(Base):
    __tablename__ = "attendance_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_key: Mapped[str] = mapped_column(String(120), unique=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("attendance_records.id", ondelete="CASCADE"))
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AttendanceDeletion(Base):
    __tablename__ = "attendance_deletions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    records: Mapped[list] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    restored_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str] = mapped_column(String(80))
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


Index("ix_session_date_category", AttendanceSession.local_date, AttendanceSession.category)
Index("ix_station_day", AttendanceSession.station_day, unique=True)
