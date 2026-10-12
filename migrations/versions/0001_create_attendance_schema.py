"""Create attendance schema"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "catalog",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "name"),
    )
    op.create_table(
        "holidays",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.PrimaryKeyConstraint("day"),
    )
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bucket", sa.String(length=64), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_login_attempts_at"), "login_attempts", ["at"], unique=False)
    op.create_index(op.f("ix_login_attempts_bucket"), "login_attempts", ["bucket"], unique=False)
    op.create_table(
        "policies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column("index_version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_table(
        "attendance_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=False),
        sa.Column("cutoff_at", sa.DateTime(), nullable=False),
        sa.Column("grace_minutes", sa.Integer(), nullable=False),
        sa.Column("checkout_enabled", sa.Boolean(), nullable=False),
        sa.Column("finalized", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_attendance_sessions_local_date"),
        "attendance_sessions",
        ["local_date"],
        unique=False,
    )
    op.create_index(
        "ix_session_date_category", "attendance_sessions", ["local_date", "category"], unique=False
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("entity", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.String(length=80), nullable=False),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"], unique=False)
    op.create_table(
        "login_sessions",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index(op.f("ix_login_sessions_user_id"), "login_sessions", ["user_id"], unique=False)
    op.create_table(
        "people",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("institutional_id", sa.String(length=80), nullable=False),
        sa.Column("full_name", sa.String(length=160), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("joined_on", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("is_minor", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["catalog.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("institutional_id"),
    )
    op.create_index(op.f("ix_people_category"), "people", ["category"], unique=False)
    op.create_index(op.f("ix_people_full_name"), "people", ["full_name"], unique=False)
    op.create_table(
        "attendance_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("verification", sa.String(length=30), nullable=False),
        sa.Column("check_in", sa.DateTime(), nullable=True),
        sa.Column("check_out", sa.DateTime(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["people.id"],
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["attendance_sessions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "person_id"),
    )
    op.create_index(
        op.f("ix_attendance_records_person_id"), "attendance_records", ["person_id"], unique=False
    )
    op.create_index(
        op.f("ix_attendance_records_session_id"), "attendance_records", ["session_id"], unique=False
    )
    op.create_table(
        "consents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("basis", sa.String(length=40), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("guardian", sa.String(length=160), nullable=True),
        sa.Column("recorded_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["recorded_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_consents_person_id"), "consents", ["person_id"], unique=False)
    op.create_table(
        "leave_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("approved_by", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["people.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_leave_records_person_id"), "leave_records", ["person_id"], unique=False
    )
    op.create_table(
        "person_details",
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.String(length=80), nullable=True),
        sa.Column("employee_id", sa.String(length=80), nullable=True),
        sa.Column("class_id", sa.Integer(), nullable=True),
        sa.Column("section", sa.String(length=80), nullable=True),
        sa.Column("academic_year", sa.String(length=40), nullable=True),
        sa.Column("semester", sa.String(length=40), nullable=True),
        sa.Column("roll_number", sa.String(length=80), nullable=True),
        sa.Column("designation", sa.String(length=120), nullable=True),
        sa.Column("shift_id", sa.Integer(), nullable=True),
        sa.Column("assigned_courses", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["class_id"],
            ["catalog.id"],
        ),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["shift_id"],
            ["catalog.id"],
        ),
        sa.PrimaryKeyConstraint("person_id"),
    )
    op.create_table(
        "profile_photos",
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("encrypted_jpeg", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("person_id"),
    )
    op.create_table(
        "session_members",
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["people.id"],
        ),
        sa.ForeignKeyConstraint(["session_id"], ["attendance_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id", "person_id"),
    )
    op.create_table(
        "attendance_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_key", sa.String(length=120), nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(["record_id"], ["attendance_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_key"),
    )
    op.create_table(
        "enrollments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("consent_id", sa.Integer(), nullable=False),
        sa.Column("recorded_by", sa.Integer(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["consent_id"],
            ["consents.id"],
        ),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["recorded_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_enrollments_person_id"), "enrollments", ["person_id"], unique=False)
    op.create_table(
        "face_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("enrollment_id", sa.Integer(), nullable=False),
        sa.Column("encrypted_vector", sa.LargeBinary(), nullable=False),
        sa.Column("model_version", sa.String(length=80), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["enrollment_id"], ["enrollments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_face_templates_expires_at"), "face_templates", ["expires_at"], unique=False
    )
    op.create_index(
        op.f("ix_face_templates_person_id"), "face_templates", ["person_id"], unique=False
    )


def downgrade():
    op.drop_index(op.f("ix_face_templates_person_id"), table_name="face_templates")
    op.drop_index(op.f("ix_face_templates_expires_at"), table_name="face_templates")
    op.drop_table("face_templates")
    op.drop_index(op.f("ix_enrollments_person_id"), table_name="enrollments")
    op.drop_table("enrollments")
    op.drop_table("attendance_events")
    op.drop_table("session_members")
    op.drop_table("profile_photos")
    op.drop_table("person_details")
    op.drop_index(op.f("ix_leave_records_person_id"), table_name="leave_records")
    op.drop_table("leave_records")
    op.drop_index(op.f("ix_consents_person_id"), table_name="consents")
    op.drop_table("consents")
    op.drop_index(op.f("ix_attendance_records_session_id"), table_name="attendance_records")
    op.drop_index(op.f("ix_attendance_records_person_id"), table_name="attendance_records")
    op.drop_table("attendance_records")
    op.drop_index(op.f("ix_people_full_name"), table_name="people")
    op.drop_index(op.f("ix_people_category"), table_name="people")
    op.drop_table("people")
    op.drop_index(op.f("ix_login_sessions_user_id"), table_name="login_sessions")
    op.drop_table("login_sessions")
    op.drop_index(op.f("ix_audit_logs_action"), table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_session_date_category", table_name="attendance_sessions")
    op.drop_index(op.f("ix_attendance_sessions_local_date"), table_name="attendance_sessions")
    op.drop_table("attendance_sessions")
    op.drop_table("users")
    op.drop_table("policies")
    op.drop_index(op.f("ix_login_attempts_bucket"), table_name="login_attempts")
    op.drop_index(op.f("ix_login_attempts_at"), table_name="login_attempts")
    op.drop_table("login_attempts")
    op.drop_table("holidays")
    op.drop_table("catalog")
