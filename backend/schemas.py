from datetime import date, datetime
from enum import StrEnum
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Password = Annotated[str, StringConstraints(strip_whitespace=False)]


class Role(StrEnum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    TEACHER = "teacher"
    OPERATOR = "staff_operator"
    VIEWER = "viewer"


class Category(StrEnum):
    STUDENT = "student"
    TEACHER = "teacher"
    STAFF = "staff"
    OTHER = "other"


class Status(StrEnum):
    PRESENT = "present"
    LATE = "late"
    ABSENT = "absent"
    EXCUSED = "excused"
    LEAVE = "on_leave"
    HOLIDAY = "holiday"
    PENDING = "pending_verification"


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True)


class LoginInput(Input):
    username: str = Field(min_length=1, max_length=80)
    password: Password = Field(min_length=1, max_length=256, repr=False)


class UserInput(Input):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9_.@-]+$")
    password: Password = Field(min_length=12, max_length=128, repr=False)
    role: Role


class PasswordInput(Input):
    current_password: Password = Field(repr=False)
    new_password: Password = Field(min_length=12, max_length=128, repr=False)


class DetailsInput(Input):
    student_id: str | None = Field(default=None, max_length=80)
    employee_id: str | None = Field(default=None, max_length=80)
    class_id: int | None = None
    section: str | None = Field(default=None, max_length=80)
    academic_year: str | None = Field(default=None, max_length=40)
    semester: str | None = Field(default=None, max_length=40)
    roll_number: str | None = Field(default=None, max_length=80)
    designation: str | None = Field(default=None, max_length=120)
    shift_id: int | None = None
    assigned_courses: list[int] = Field(default_factory=list, max_length=100)


class PersonInput(Input):
    institutional_id: str = Field(min_length=1, max_length=80, pattern=r"^[\w.-]+$")
    full_name: str = Field(min_length=2, max_length=160)
    category: Category
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    department_id: int | None = None
    active: bool = True
    joined_on: date
    notes: str = Field(default="", max_length=3000)
    is_minor: bool = False
    details: DetailsInput = Field(default_factory=DetailsInput)

    @model_validator(mode="after")
    def category_fields(self):
        d = self.details
        if self.category == Category.STUDENT:
            if d.employee_id or d.designation or d.shift_id:
                raise ValueError("Employee fields do not apply to students")
        elif any([d.student_id, d.class_id, d.section, d.academic_year, d.semester, d.roll_number]):
            raise ValueError("Student fields only apply to students")
        return self


class ConsentInput(Input):
    basis: str = Field(pattern=r"^(explicit_consent|institutional_authorization)$")
    statement: str = Field(min_length=20, max_length=3000)
    guardian: str | None = Field(default=None, max_length=160)


class SessionInput(Input):
    name: str = Field(min_length=2, max_length=160)
    category: Category
    timezone: str = "Asia/Dhaka"
    starts_at: datetime
    ends_at: datetime
    cutoff_at: datetime
    grace_minutes: int = Field(default=10, ge=0, le=180)
    checkout_enabled: bool = False
    person_ids: list[int] = Field(min_length=1, max_length=10000)

    @field_validator("starts_at", "ends_at", "cutoff_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("Timestamp must contain a timezone offset")
        return value

    @model_validator(mode="after")
    def dates(self):
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError("Unknown IANA timezone") from error
        if (
            not self.starts_at < self.ends_at
            or not self.starts_at <= self.cutoff_at <= self.ends_at
        ):
            raise ValueError("Session must start before end; cutoff must be within the session")
        if (self.ends_at - self.starts_at).total_seconds() > 86400:
            raise ValueError("A session cannot exceed 24 hours")
        if len(self.person_ids) != len(set(self.person_ids)):
            raise ValueError("Session roster contains duplicate people")
        return self


class CorrectionInput(Input):
    session_id: int
    person_id: int
    status: Status
    check_in: datetime | None = None
    check_out: datetime | None = None
    reason: str = Field(min_length=5, max_length=2000)
    expected_version: int = Field(default=0, ge=0)

    @field_validator("check_in", "check_out")
    @classmethod
    def aware(cls, value):
        if value and value.tzinfo is None:
            raise ValueError("Timestamp must contain a timezone offset")
        return value

    @model_validator(mode="after")
    def dates(self):
        if self.check_out and (not self.check_in or self.check_out <= self.check_in):
            raise ValueError("Checkout must follow check-in")
        if self.status in {Status.PRESENT, Status.LATE} and not self.check_in:
            raise ValueError("Present and late records require a check-in")
        if self.status in {Status.ABSENT, Status.LEAVE, Status.HOLIDAY, Status.EXCUSED}:
            if self.check_in or self.check_out:
                raise ValueError("Non-attending statuses cannot contain attendance times")
        return self


class LeaveInput(Input):
    person_id: int
    starts_on: date
    ends_on: date
    reason: str = Field(min_length=5, max_length=2000)

    @model_validator(mode="after")
    def dates(self):
        if self.ends_on < self.starts_on:
            raise ValueError("Leave end precedes start")
        return self


class PolicyInput(Input):
    station_name: str = Field(default="Live attendance station", min_length=2, max_length=100)
    station_auto_mark: bool = True
    similarity_threshold: float = Field(default=0.8, ge=0.5, le=0.99)
    ambiguity_margin: float = Field(default=0.08, ge=0.02, le=0.5)
    stable_observations: int = Field(default=3, ge=3, le=10)
    stable_seconds: float = Field(default=1.0, ge=1, le=10)
    processing_width: int = Field(default=640, ge=320, le=1280)
    processing_interval: float = Field(default=0.5, ge=0.2, le=5)
    template_retention_days: int = Field(default=365, ge=1, le=3650)
    attendance_retention_days: int = Field(default=730, ge=30, le=3650)
    working_days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    min_face_pixels: int = Field(default=70, ge=40, le=300)
    min_blur_variance: float = Field(default=40, ge=10, le=500)

    @field_validator("working_days")
    @classmethod
    def weekdays(cls, values):
        if not values or any(v < 0 or v > 6 for v in values) or len(set(values)) != len(values):
            raise ValueError("Use unique weekday numbers from 0 (Monday) to 6 (Sunday)")
        return values


class ReasonInput(Input):
    reason: str = Field(min_length=5, max_length=2000)


class CatalogInput(Input):
    kind: str = Field(pattern=r"^(department|class|course|shift)$")
    name: str = Field(min_length=1, max_length=120)
    details: dict[str, str] = Field(default_factory=dict)


class StreamInput(Input):
    session_id: int


class HolidayInput(Input):
    day: date
    name: str = Field(min_length=2, max_length=160)
