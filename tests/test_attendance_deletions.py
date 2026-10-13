from datetime import timedelta
from unittest.mock import Mock

import numpy as np
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from test_station import enroll_fixture

from backend.db import utcnow
from backend.models import (
    AttendanceDeletion,
    AttendanceEvent,
    AuditLog,
    FaceTemplate,
    Person,
    User,
)


def record_arrival(client, session, person):
    response = client.post(
        "/attendance/correct",
        json={
            "session_id": session["id"],
            "person_id": person["id"],
            "status": "present",
            "check_in": session["starts_at"],
            "reason": "Arrival verified for regression test",
        },
    )
    assert response.status_code == 200, response.text


def period(session):
    return {"start": session["local_date"], "end": session["local_date"]}


def delete_row(client, row):
    return client.request(
        "DELETE",
        f"/attendance/{row['record_id']}",
        json={
            "expected_version": row["version"],
            "expected_updated_at": row["updated_at"],
        },
    )


def test_reset_preserves_profiles_faces_and_supports_audited_restore(
    app, client, person, attendance_session
):
    enroll_fixture(app, person["id"])
    record_arrival(client, attendance_session, person)
    params = period(attendance_session)
    before = client.get("/attendance", params=params).json()[0]
    with app.state.sessions() as db:
        original_events = db.scalar(select(func.count()).select_from(AttendanceEvent))
    response = client.delete("/attendance", params=params)
    assert response.status_code == 200
    assert response.json()["deleted"] == 1
    deletion_id = response.json()["deletion_id"]
    assert client.get("/attendance", params=params).json() == []
    overview = client.get("/overview").json()
    assert overview["checked_in_people"] == 0
    assert sum(overview["people"].values()) == 1
    assert overview["attendance"] == {}
    assert client.get(f"/people/{person['id']}").json()["enrolled"]
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(FaceTemplate)) == 1
        assert db.scalar(select(func.count()).select_from(AttendanceEvent)) == 0
        assert db.get(Person, person["id"]).active
        assert db.scalar(select(AuditLog).where(AuditLog.action == "attendance_deleted"))
    assert client.post(f"/attendance-deletions/{deletion_id}/restore").json() == {"restored": 1}
    restored = client.get("/attendance", params=params).json()[0]
    for key in ("status", "check_in", "check_out", "verification", "person_id", "session_id"):
        assert restored[key] == before[key]
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(AttendanceEvent)) == original_events
        assert db.scalar(select(AuditLog).where(AuditLog.action == "attendance_restored"))
    assert client.get("/attendance-deletions").json() == []
    assert client.post(f"/attendance-deletions/{deletion_id}/restore").status_code == 409


def test_row_delete_is_scoped_and_rejects_stale_clicks(
    client, person, attendance_session, session_payload
):
    second = client.post("/sessions", json={**session_payload, "name": "Second class"}).json()
    for session in (attendance_session, second):
        record_arrival(client, session, person)
    params = period(attendance_session)
    rows = client.get("/attendance", params=params).json()
    assert client.get("/overview").json()["checked_in_people"] == 1
    assert delete_row(client, rows[0]).json()["deleted"] == 1
    assert len(client.get("/attendance", params=params).json()) == 1
    assert delete_row(client, rows[0]).status_code == 404
    row = client.get("/attendance", params=params).json()[0]
    assert (
        client.post(
            "/attendance/correct",
            json={
                "session_id": row["session_id"],
                "person_id": person["id"],
                "status": "late",
                "check_in": row["check_in"],
                "reason": "Corrected after arrival review",
                "expected_version": row["version"],
            },
        ).status_code
        == 200
    )
    assert delete_row(client, row).status_code == 409
    assert client.get("/attendance", params=params).json()[0]["status"] == "late"


def test_reused_record_id_cannot_be_deleted_by_old_row(client, person, attendance_session):
    record_arrival(client, attendance_session, person)
    row = client.get("/attendance", params=period(attendance_session)).json()[0]
    assert delete_row(client, row).status_code == 200
    record_arrival(client, attendance_session, person)
    new_row = client.get("/attendance", params=period(attendance_session)).json()[0]
    assert new_row["record_id"] == row["record_id"]  # SQLite reuses the highest deleted ID.
    assert new_row["version"] == row["version"]
    assert delete_row(client, row).status_code == 409


def test_restore_does_not_overwrite_new_checkins(client, person, person_payload, session_payload):
    other = client.post("/people", json={**person_payload, "institutional_id": "STU-2"}).json()
    session = client.post(
        "/sessions", json={**session_payload, "person_ids": [person["id"], other["id"]]}
    ).json()
    for p in (person, other):
        record_arrival(client, session, p)
    params = period(session)
    deletion_id = client.delete("/attendance", params=params).json()["deletion_id"]
    record_arrival(client, session, person)
    assert client.post(f"/attendance-deletions/{deletion_id}/restore").status_code == 409
    rows = client.get("/attendance", params=params).json()
    assert [row["person_id"] for row in rows] == [person["id"]]
    assert len(client.get("/attendance-deletions").json()) == 1


def test_reset_respects_date_person_and_session_filters(
    client, person, person_payload, session_payload
):
    other = client.post("/people", json={**person_payload, "institutional_id": "STU-2"}).json()
    now = utcnow()
    sessions = []
    for offset in (0, 1):
        sessions.append(
            client.post(
                "/sessions",
                json={
                    **session_payload,
                    "person_ids": [person["id"], other["id"]],
                    "starts_at": (now - timedelta(days=offset, hours=1)).isoformat(),
                    "cutoff_at": (now - timedelta(days=offset) + timedelta(minutes=30)).isoformat(),
                    "ends_at": (now - timedelta(days=offset) + timedelta(hours=1)).isoformat(),
                },
            ).json()
        )
    for session in sessions:
        for p in (person, other):
            record_arrival(client, session, p)
    params = {**period(sessions[0]), "person_id": person["id"], "session_id": sessions[0]["id"]}
    assert client.delete("/attendance", params=params).json()["deleted"] == 1
    assert [
        r["person_id"] for r in client.get("/attendance", params=period(sessions[0])).json()
    ] == [other["id"]]
    assert len(client.get("/attendance", params=period(sessions[1])).json()) == 2
    assert client.delete("/attendance").status_code == 422


@pytest.mark.parametrize(
    "role,allowed",
    [("admin", True), ("teacher", False), ("staff_operator", False), ("viewer", False)],
)
def test_delete_and_recovery_permissions(client, person, attendance_session, role, allowed):
    record_arrival(client, attendance_session, person)
    params = period(attendance_session)
    row = client.get("/attendance", params=params).json()[0]
    client.post("/users", json={"username": role, "password": "test-password-123", "role": role})
    token = client.post(
        "/auth/login", json={"username": role, "password": "test-password-123"}
    ).json()["token"]
    client.headers["Authorization"] = "Bearer " + token
    response = delete_row(client, row)
    assert response.status_code == (200 if allowed else 403)
    assert client.get("/attendance-deletions").status_code == (200 if allowed else 403)
    assert client.delete("/attendance", params=params).status_code == (200 if allowed else 403)
    if allowed:
        assert (
            client.post(
                f"/attendance-deletions/{response.json()['deletion_id']}/restore"
            ).status_code
            == 200
        )
    else:
        assert client.post("/attendance-deletions/unavailable/restore").status_code == 403
        assert len(client.get("/attendance", params=params).json()) == 1


def test_reset_stops_all_affected_streams_and_allows_explicit_restart(
    app, client, person, attendance_session
):
    enroll_fixture(app, person["id"])
    service = app.state.vision
    service.load = Mock()
    service.analyze = Mock(return_value=[])
    first = client.post("/station/start").json()
    second = client.post("/station/start").json()
    scheduled = client.post("/vision/streams", json={"session_id": attendance_session["id"]}).json()
    station = client.get("/station").json()["session"]
    record_arrival(client, station, person)
    response = client.delete("/attendance", params={**period(station), "session_id": station["id"]})
    assert response.json()["deleted"] == 1
    assert scheduled["stream_id"] in service.streams
    for stream in (first, second):
        assert stream["stream_id"] not in service.streams
        with app.state.sessions() as db, pytest.raises(HTTPException) as error:
            service.process_frame(
                db, db.get(User, 1), stream["stream_id"], np.zeros((160, 160, 3), np.uint8)
            )
        assert error.value.status_code == 404
    new = client.post("/station/start").json()
    assert new["stream_id"] not in {first["stream_id"], second["stream_id"]}
    assert new["session_id"] == station["id"]
    # A reset must also stop a running camera before its first successful check-in.
    assert client.delete("/attendance", params=period(station)).json()["deleted"] == 0
    assert service.streams == {}


def test_recovery_expiration_and_retention(app, client, person, attendance_session, monkeypatch):
    from scripts import manage

    record_arrival(client, attendance_session, person)
    deletion_id = client.delete("/attendance", params=period(attendance_session)).json()[
        "deletion_id"
    ]
    with app.state.sessions() as db:
        db.get(AttendanceDeletion, deletion_id).created_at = utcnow() - timedelta(days=31)
        db.commit()
    assert client.get("/attendance-deletions").json() == []
    assert client.post(f"/attendance-deletions/{deletion_id}/restore").status_code == 404
    monkeypatch.setattr(manage, "get_settings", lambda: app.state.settings)
    manage.retention()
    with app.state.sessions() as db:
        assert db.get(AttendanceDeletion, deletion_id)
    manage.retention(apply=True)
    with app.state.sessions() as db:
        assert db.get(AttendanceDeletion, deletion_id) is None
        assert db.get(Person, person["id"]).active


def test_removed_people_are_not_counted_as_registered(client, person, attendance_session):
    record_arrival(client, attendance_session, person)
    assert sum(client.get("/overview").json()["people"].values()) == 1
    assert (
        client.request(
            "DELETE", f"/people/{person['id']}", json={"reason": "Removed from institution"}
        ).status_code
        == 204
    )
    assert sum(client.get("/overview").json()["people"].values()) == 0
    assert len(client.get("/attendance", params=period(attendance_session)).json()) == 1
