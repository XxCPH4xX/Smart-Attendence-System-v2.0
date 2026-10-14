from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from backend.db import make_engine


def test_people_upgrade_preserves_existing_attendance_and_faces(
    app, client, person, attendance_session, monkeypatch
):
    from test_attendance_deletions import record_arrival
    from test_station import enroll_fixture

    from backend.config import get_settings

    enroll_fixture(app, person["id"])
    record_arrival(client, attendance_session, person)
    monkeypatch.setenv("ATTENDANCE_DATABASE_URL", app.state.settings.database_url)
    get_settings.cache_clear()
    config = Config(str(Path("alembic.ini").resolve()))
    engine = make_engine(app.state.settings.database_url)
    tables = [
        "people",
        "person_details",
        "consents",
        "enrollments",
        "face_templates",
        "attendance_records",
        "attendance_events",
        "attendance_sessions",
        "session_members",
        "audit_logs",
    ]
    try:
        command.stamp(config, "head")
        command.downgrade(config, "0002")
        with engine.connect() as db:
            snapshots = {
                table: db.execute(text(f"SELECT * FROM {table} ORDER BY 1")).all()
                for table in tables
            }
        command.upgrade(config, "head")
        command.check(config)
        with engine.connect() as db:
            for table in tables:
                rows = db.execute(text(f"SELECT * FROM {table} ORDER BY 1")).all()
                if table == "people":
                    assert [tuple(row[:-2]) for row in rows] == [
                        tuple(row) for row in snapshots[table]
                    ]
                    assert rows[0][-2:] == (None, None)
                elif table == "attendance_sessions":
                    assert [tuple(row[:-1]) for row in rows] == [
                        tuple(row) for row in snapshots[table]
                    ]
                    assert all(row[-1] is None for row in rows)
                else:
                    assert rows == snapshots[table]
            assert db.execute(text("PRAGMA foreign_key_check")).all() == []
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_migrations_round_trip(tmp_path, monkeypatch):
    from backend.config import get_settings

    url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("ATTENDANCE_DATABASE_URL", url)
    get_settings.cache_clear()
    config = Config(str(Path("alembic.ini").resolve()))
    try:
        command.upgrade(config, "head")
        command.check(config)
        engine = make_engine(url)
        assert "face_templates" in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM people")).scalar() == 0
        engine.dispose()
        command.downgrade(config, "base")
        command.upgrade(config, "head")
    finally:
        get_settings.cache_clear()


def test_invalid_cli_password_is_not_disclosed(monkeypatch, capsys):
    import traceback

    import pytest

    from scripts import manage

    password = "short-test"
    monkeypatch.setattr("builtins.input", lambda prompt: "test_admin")
    monkeypatch.setattr(manage.getpass, "getpass", lambda prompt: password)
    monkeypatch.setattr(
        manage, "make_engine", lambda url: pytest.fail("Invalid input must not open the database")
    )
    for reset in (False, True):
        with pytest.raises(SystemExit) as caught:
            manage.account(reset=reset)
        assert "at least 12 characters" in str(caught.value)
        assert "Account was not saved" in str(caught.value)
        rendered = "".join(traceback.format_exception(caught.value))
        output = capsys.readouterr()
        assert password not in rendered + output.out + output.err
