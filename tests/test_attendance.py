from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.attendance import finalize, recognized_checkin
from backend.db import utcnow
from backend.models import AttendanceRecord, AttendanceSession, AuditLog, Person, User


def checkin(app, session, person, event="camera-event", now=None):
    with app.state.sessions() as db:
        return recognized_checkin(db, db.get(User, 1), session["id"], person["id"], event, now)


def test_duplicate_prevention(app, attendance_session, person):
    first, _ = checkin(app, attendance_session, person)
    second, result = checkin(app, attendance_session, person, "second-event")
    assert first.id == second.id
    assert result == "Already checked in"
    assert first.status == "pending_verification"
    assert second.check_out is None
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(AttendanceRecord)) == 1


def test_parallel_checkin_database_guard(app, attendance_session, person):
    barrier = Barrier(2)

    def worker(index):
        barrier.wait()
        try:
            return checkin(app, attendance_session, person, f"event-{index}")[0].id
        except IntegrityError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(worker, range(2)))
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(AttendanceRecord)) == 1


def test_approve_and_audit(app, client, attendance_session, person):
    record, _ = checkin(app, attendance_session, person)
    response = client.post(
        f"/attendance/{record.id}/approve", json={"reason": "Verified at desk in person"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "present"
    assert response.json()["verification"] == "staff_verified"
    assert (
        client.post(f"/attendance/{record.id}/approve", json={"reason": "Verify again"}).status_code
        == 409
    )
    logs = client.get("/audit").json()
    log = next(e for e in logs if e["action"] == "attendance_verified")
    assert log["before"]["status"] == "pending_verification"
    assert log["after"]["status"] == "present"


def test_late_rule(app, client, attendance_session, person):
    record, _ = checkin(app, attendance_session, person, now=utcnow() + timedelta(minutes=15))
    response = client.post(
        f"/attendance/{record.id}/approve", json={"reason": "Confirmed late arrival"}
    )
    assert response.json()["status"] == "late"


def test_inactive_or_outside_window_rejected(app, attendance_session, person):
    with pytest.raises(HTTPException, match="Outside"):
        checkin(app, attendance_session, person, now=utcnow() + timedelta(days=1))
    with app.state.sessions() as db:
        db.get(Person, person["id"]).active = False
        db.commit()
    with pytest.raises(HTTPException, match="inactive"):
        checkin(app, attendance_session, person)


def test_manual_correction_and_optimistic_conflict(client, attendance_session, person):
    data = dict(
        session_id=attendance_session["id"],
        person_id=person["id"],
        status="present",
        check_in=attendance_session["starts_at"],
        reason="Manual attendance alternative",
        expected_version=0,
    )
    result = client.post("/attendance/correct", json=data)
    assert result.status_code == 200
    assert client.post("/attendance/correct", json=data).status_code == 409
    data.update(status="excused", check_in=None, expected_version=result.json()["version"])
    assert client.post("/attendance/correct", json=data).status_code == 200
    log = next(x for x in client.get("/audit").json() if x["action"] == "attendance_corrected")
    assert log["before"]["status"] == "present"
    assert log["after"]["status"] == "excused"


def test_checkout_requires_enabled_and_ordered(client, attendance_session, person, app):
    data = dict(
        session_id=attendance_session["id"],
        person_id=person["id"],
        status="present",
        check_in=attendance_session["starts_at"],
        check_out=attendance_session["ends_at"],
        reason="Authorized end of shift",
        expected_version=0,
    )
    assert client.post("/attendance/correct", json=data).status_code == 409
    with app.state.sessions() as db:
        db.get(AttendanceSession, attendance_session["id"]).checkout_enabled = True
        db.commit()
    response = client.post("/attendance/correct", json=data)
    assert response.status_code == 200
    data.update(check_out=data["check_in"], expected_version=response.json()["version"])
    assert client.post("/attendance/correct", json=data).status_code == 422


@pytest.mark.parametrize("exception", ["absent", "on_leave", "holiday"])
def test_finalize_applies_roster_exceptions(client, app, attendance_session, person, exception):
    day = attendance_session["local_date"]
    if exception == "on_leave":
        assert (
            client.post(
                "/leaves",
                json={
                    "person_id": person["id"],
                    "starts_on": day,
                    "ends_on": day,
                    "reason": "Approved scheduled leave",
                },
            ).status_code
            == 201
        )
    if exception == "holiday":
        assert (
            client.post("/holidays", json={"day": day, "name": "Institution holiday"}).status_code
            == 200
        )
    if exception != "absent":
        with pytest.raises(HTTPException):
            checkin(app, attendance_session, person)
    assert client.post(f"/sessions/{attendance_session['id']}/finalize").status_code == 409
    with app.state.sessions() as db:
        assert (
            finalize(
                db, db.get(User, 1), attendance_session["id"], now=utcnow() + timedelta(days=1)
            )
            == 1
        )
        assert (
            finalize(
                db, db.get(User, 1), attendance_session["id"], now=utcnow() + timedelta(days=1)
            )
            == 0
        )
        record = db.scalar(select(AttendanceRecord))
        assert record.status == exception


def test_missing_is_not_absent(client, attendance_session):
    day = attendance_session["local_date"]
    assert client.get("/attendance", params={"start": day, "end": day}).json() == []


def test_session_validation(client, session_payload):
    session_payload["ends_at"] = session_payload["starts_at"]
    assert client.post("/sessions", json=session_payload).status_code == 422
    session_payload["ends_at"] = (utcnow() + timedelta(hours=2)).isoformat()
    session_payload["person_ids"] = [999]
    assert client.post("/sessions", json=session_payload).status_code == 422
    session_payload["starts_at"] = "2026-10-12T09:00:00"
    assert client.post("/sessions", json=session_payload).status_code == 422


def test_person_with_roster_cannot_be_deleted(client, attendance_session, person, person_payload):
    person_payload["active"] = False
    client.put(f"/people/{person['id']}", json=person_payload)
    assert (
        client.request(
            "DELETE", f"/people/{person['id']}", json={"reason": "Delete retained person"}
        ).status_code
        == 409
    )


def test_correction_rollback_on_error(client, app, attendance_session, person):
    data = dict(
        session_id=attendance_session["id"],
        person_id=person["id"],
        status="present",
        check_in=(utcnow() + timedelta(days=1)).isoformat(),
        reason="Invalid future timestamp",
    )
    assert client.post("/attendance/correct", json=data).status_code == 422
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(AttendanceRecord)) == 0
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "attendance_corrected")
            )
            == 0
        )
