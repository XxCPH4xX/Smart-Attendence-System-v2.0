from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import httpx
import numpy as np
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from backend.attendance import finalize, recognized_checkin
from backend.db import utcnow
from backend.models import (
    AttendanceRecord,
    AttendanceSession,
    Consent,
    Enrollment,
    FaceTemplate,
    Person,
    User,
)
from backend.station import daily_station
from vision.camera import RemoteProcessor


def enroll_fixture(app, person_id):
    with app.state.sessions() as db:
        consent = Consent(
            person_id=person_id,
            basis="explicit_consent",
            statement="Authorized synthetic enrollment fixture",
            recorded_by=1,
        )
        db.add(consent)
        db.flush()
        enrollment = Enrollment(
            person_id=person_id, consent_id=consent.id, recorded_by=1, sample_count=3
        )
        db.add(enrollment)
        db.flush()
        db.add(
            FaceTemplate(
                person_id=person_id,
                enrollment_id=enrollment.id,
                encrypted_vector=b"synthetic-test-only",
                model_version="test",
                expires_at=utcnow() + timedelta(days=365),
            )
        )
        db.commit()


def test_daily_station_reuses_day_and_accepts_all_categories(app, client, person):
    staff = client.post(
        "/people",
        json={
            "full_name": "Test Staff",
            "institutional_id": "STAFF-1",
            "category": "staff",
            "joined_on": "2026-01-01",
        },
    ).json()
    for p in [person, staff]:
        enroll_fixture(app, p["id"])
    assert client.get("/station").json()["enrolled_people"] == 2
    with app.state.sessions() as db:
        user = db.get(User, 1)
        session = daily_station(db, user, "Asia/Dhaka")
        assert daily_station(db, user, "Asia/Dhaka").id == session.id
        for p in [person, staff]:
            record, feedback = recognized_checkin(db, user, session.id, p["id"], f"first-{p['id']}")
            assert record.status == "present"
            assert record.verification == "face_matched"
            assert feedback == "Attendance marked"
            assert (
                recognized_checkin(db, user, session.id, p["id"], f"repeat-{p['id']}")[0].id
                == record.id
            )
        assert db.scalar(select(func.count()).select_from(AttendanceRecord)) == 2
        with pytest.raises(HTTPException, match="Daily stations"):
            finalize(db, user, session.id, now=utcnow() + timedelta(days=1))


def test_station_rejects_unenrolled_and_deactivated_people(app, client, person):
    with app.state.sessions() as db:
        user = db.get(User, 1)
        session_id = daily_station(db, user, "Asia/Dhaka").id
        with pytest.raises(HTTPException, match="authorized face enrollment"):
            recognized_checkin(db, user, session_id, person["id"], "unenrolled")
    enroll_fixture(app, person["id"])
    with app.state.sessions() as db:
        db.get(Person, person["id"]).active = False
        db.commit()
        with pytest.raises(HTTPException, match="authorized face enrollment"):
            recognized_checkin(db, db.get(User, 1), session_id, person["id"], "inactive")


def test_station_can_require_review(app, client, person):
    enroll_fixture(app, person["id"])
    policy = client.get("/settings").json()["policy"]
    policy["station_auto_mark"] = False
    policy["station_name"] = "Reception"
    assert client.put("/settings", json=policy).status_code == 200
    with app.state.sessions() as db:
        user = db.get(User, 1)
        station = daily_station(db, user, "Asia/Dhaka")
        record, _ = recognized_checkin(db, user, station.id, person["id"], "review")
        assert record.status == "pending_verification"
        assert record.verification == "pending"


def test_station_stream_runs_through_midnight_without_restarting(app, client, person, monkeypatch):
    enroll_fixture(app, person["id"])
    service = app.state.vision
    service.load = Mock()
    service.analyze = Mock(
        return_value=[
            {"box": [0, 0, 100, 100], "person_id": person["id"], "name": "Test", "label": "Student"}
        ]
    )
    now = [datetime(2026, 10, 12, 17, 59, 58, tzinfo=UTC)]
    for module in ["backend.station", "backend.attendance", "backend.api.vision"]:
        monkeypatch.setattr(module + ".utcnow", lambda: now[0])
    clock = [1000.0]
    monkeypatch.setattr("backend.biometrics.time.monotonic", lambda: clock[0])
    start = client.post("/station/start")
    assert start.status_code == 201
    key = start.json()["stream_id"]
    with app.state.sessions() as db:
        for offset in [0, 0.6, 1.2]:
            clock[0] = 1000 + offset
            result = service.process_frame(
                db, db.get(User, 1), key, np.zeros((160, 160, 3), np.uint8)
            )
        assert result["faces"][0]["attendance_status"] == "present"
        now[0] += timedelta(seconds=3)
        clock[0] += 0.6
        result = service.process_frame(db, db.get(User, 1), key, np.zeros((160, 160, 3), np.uint8))
        assert result["faces"][0]["attendance_status"] == "present"
        assert db.scalar(select(func.count()).select_from(AttendanceRecord)) == 2
        assert db.scalar(select(func.count()).select_from(AttendanceSession)) == 2
    # Reopening the station on the same date cannot make another daily session.
    assert client.post("/station/start").status_code == 201
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(AttendanceSession)) == 2


def test_station_does_not_accept_unknown_or_unstable_faces(app, client, person, monkeypatch):
    enroll_fixture(app, person["id"])
    service = app.state.vision
    service.load = Mock()
    face = {"box": [0, 0, 100, 100], "person_id": None, "name": "Unknown", "label": "Unregistered"}
    service.analyze = Mock(return_value=[face])
    clock = [1000.0]
    monkeypatch.setattr("backend.biometrics.time.monotonic", lambda: clock[0])
    key = client.post("/station/start").json()["stream_id"]
    with app.state.sessions() as db:
        for offset in [0, 0.6, 1.2]:
            clock[0] = 1000 + offset
            service.process_frame(db, db.get(User, 1), key, np.zeros((160, 160, 3), np.uint8))
        face["person_id"] = person["id"]
        clock[0] += 0.6
        service.process_frame(db, db.get(User, 1), key, np.zeros((160, 160, 3), np.uint8))
        assert db.scalar(select(func.count()).select_from(AttendanceRecord)) == 0


def test_reset_or_expired_station_requires_explicit_restart():
    calls = []

    def respond(request):
        calls.append(request.url.path)
        if request.url.path == "/station/start":
            return httpx.Response(201, json={"stream_id": "new"})
        return httpx.Response(404, json={"detail": "expired"})

    processor = RemoteProcessor("http://localhost", "test", "old", station=True)
    processor.client.close()
    processor.client = httpx.Client(
        base_url="http://localhost", transport=httpx.MockTransport(respond)
    )
    result = processor.infer(np.zeros((160, 160, 3), np.uint8))
    assert result["stopped"]
    assert "Start the station again" in result["error"]
    assert processor.stream_id == "old"
    processor.close()
    assert calls == ["/vision/streams/old/frame", "/vision/streams/old"]


def test_station_review_approval_is_present_not_midnight_late(app, client, person):
    enroll_fixture(app, person["id"])
    policy = client.get("/settings").json()["policy"]
    client.put("/settings", json={**policy, "station_auto_mark": False})
    with app.state.sessions() as db:
        user = db.get(User, 1)
        station = daily_station(db, user, "Asia/Dhaka")
        record, _ = recognized_checkin(db, user, station.id, person["id"], "pending")
        record_id = record.id
    result = client.post(
        f"/attendance/{record_id}/approve", json={"reason": "Verified at reception desk"}
    )
    assert result.status_code == 200
    with app.state.sessions() as db:
        assert db.get(AttendanceRecord, record_id).status == "present"


def test_station_supports_manual_alternative_without_face_enrollment(app, client, person):
    with app.state.sessions() as db:
        station = daily_station(db, db.get(User, 1), "Asia/Dhaka")
    response = client.post(
        "/attendance/correct",
        json={
            "session_id": station.id,
            "person_id": person["id"],
            "status": "present",
            "check_in": utcnow().isoformat(),
            "reason": "Verified manually without biometrics",
        },
    )
    assert response.status_code == 200, response.text
    with app.state.sessions() as db:
        record = db.scalar(select(AttendanceRecord))
        assert record.source == "manual"
        assert record.verification == "staff_verified"


def test_station_permissions(client):
    client.post(
        "/users",
        json={"username": "station-viewer", "password": "viewer-password-123", "role": "viewer"},
    )
    token = client.post(
        "/auth/login", json={"username": "station-viewer", "password": "viewer-password-123"}
    ).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/station", headers=headers).status_code == 200
    assert client.post("/station/start", headers=headers).status_code == 403
    assert (
        client.put("/settings", json={"station_auto_mark": False}, headers=headers).status_code
        == 403
    )
