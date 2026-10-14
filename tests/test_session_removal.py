from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from test_attendance_deletions import period, record_arrival

from backend.attendance import recognized_checkin
from backend.models import AttendanceSession, AuditLog, User


def test_remove_session_stops_camera_keeps_history_and_can_restore(
    app, client, person, attendance_session
):
    app.state.vision.load = Mock()
    stream = client.post("/vision/streams", json={"session_id": attendance_session["id"]}).json()
    record_arrival(client, attendance_session, person)
    before = client.get("/attendance", params=period(attendance_session)).json()
    assert client.get("/sessions").json()[0]["record_count"] == 1
    assert client.delete(f"/sessions/{attendance_session['id']}").status_code == 200
    assert stream["stream_id"] not in app.state.vision.streams
    assert client.get("/sessions").json() == []
    assert client.get("/dashboard").json()["sessions"] == []
    assert client.get("/attendance", params=period(attendance_session)).json() == before
    assert client.get(f"/sessions/{attendance_session['id']}/roster").json() == [person["id"]]
    assert client.get("/sessions", params={"archived": True}).json()[0]["archived"]
    assert client.get("/sessions", params={"archived": True, "category": "staff"}).json() == []
    assert (
        client.post("/vision/streams", json={"session_id": attendance_session["id"]}).status_code
        == 409
    )
    assert client.post(f"/sessions/{attendance_session['id']}/finalize").status_code == 409
    with app.state.sessions() as db:
        with pytest.raises(HTTPException, match="removed"):
            recognized_checkin(
                db, db.get(User, 1), attendance_session["id"], person["id"], "after-removal"
            )
        assert db.scalar(select(AuditLog).where(AuditLog.action == "session_removed"))
    response = client.post(f"/sessions/{attendance_session['id']}/restore")
    assert response.status_code == 200 and not response.json()["archived"]
    assert len(client.get("/sessions").json()) == 1
    assert client.get("/attendance", params=period(attendance_session)).json() == before


def test_removed_daily_station_stays_removed_until_new_station_is_started(app, client, person):
    app.state.vision.load = Mock()
    started = client.post("/station/start").json()
    station = client.get("/station").json()["session"]
    record_arrival(client, station, person)
    assert client.delete(f"/sessions/{station['id']}").status_code == 200
    assert started["stream_id"] not in app.state.vision.streams
    assert client.get("/station").json()["session"] is None
    assert client.get("/sessions").json() == []
    new_station = client.post("/station/start").json()
    assert new_station["session_id"] != station["id"]
    assert len(client.get("/attendance", params=period(station)).json()) == 1
    assert client.post(f"/sessions/{station['id']}/restore").status_code == 409
    with app.state.sessions() as db:
        assert db.get(AttendanceSession, station["id"]).archived_at is not None


@pytest.mark.parametrize("role", ["teacher", "staff_operator", "viewer"])
def test_session_removal_and_restore_require_schedule_permission(client, attendance_session, role):
    client.post(
        "/users",
        json={"username": "readonly_session", "password": "test-password-123", "role": role},
    )
    login = client.post(
        "/auth/login", json={"username": "readonly_session", "password": "test-password-123"}
    ).json()
    client.headers["Authorization"] = "Bearer " + login["token"]
    assert client.delete(f"/sessions/{attendance_session['id']}").status_code == 403
    assert client.post(f"/sessions/{attendance_session['id']}/restore").status_code == 403
