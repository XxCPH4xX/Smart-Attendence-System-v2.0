import json
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from sqlalchemy import func, select
from test_attendance_deletions import period, record_arrival
from test_vision import jpeg, unit

from backend.biometrics import cipher
from backend.models import (
    AuditLog,
    Consent,
    Enrollment,
    FaceTemplate,
    Person,
    PersonDetails,
    Policy,
)


def register(client, person, *, manual=True, consent=None, files=None):
    return client.post(
        "/registrations",
        data={
            "payload": json.dumps(
                {"person": person, "manual_attendance": manual, "consent": consent}
            )
        },
        files=files,
    )


def enrollment_files():
    return [
        ("files", (color + ".jpg", jpeg(color), "image/jpeg")) for color in ("red", "green", "blue")
    ]


def mock_vision(app):
    service = app.state.vision
    service.load = Mock()
    service.detector = SimpleNamespace(
        detect=lambda *args: [
            SimpleNamespace(quality_ok=True, crop=np.zeros((160, 160, 3), np.uint8))
        ],
        close=lambda: None,
    )
    service.embedder = SimpleNamespace(extract=lambda crops: np.stack([unit(0)] * len(crops)))


def snapshot(app):
    with app.state.sessions() as db:
        return {
            model.__name__: db.scalar(select(func.count()).select_from(model))
            for model in (Person, PersonDetails, Consent, Enrollment, FaceTemplate, AuditLog)
        }


AUTHORIZATION = {
    "basis": "explicit_consent",
    "statement": "Authorized enrollment for face recognition attendance.",
}


def test_manual_registration_is_complete_without_biometrics(client, app, person_payload):
    response = register(client, {**person_payload, "age": 16})
    assert response.status_code == 201, response.text
    assert response.json()["is_minor"] and not response.json()["enrolled"]
    counts = snapshot(app)
    assert counts["Person"] == counts["PersonDetails"] == 1
    assert counts["Consent"] == counts["Enrollment"] == counts["FaceTemplate"] == 0
    before = snapshot(app)
    assert register(client, person_payload).status_code == 409
    assert snapshot(app) == before


def test_atomic_face_registration_encrypts_and_rejects_duplicate_identity(
    client, app, person_payload
):
    mock_vision(app)
    response = register(
        client,
        {**person_payload, "age": 25},
        manual=False,
        consent=AUTHORIZATION,
        files=enrollment_files(),
    )
    assert response.status_code == 201, response.text
    assert response.json()["enrolled"]
    person_id = response.json()["id"]
    with app.state.sessions() as db:
        templates = list(db.scalars(select(FaceTemplate)))
        assert len(templates) == 3
        assert {entry.person_id for entry in templates} == {person_id}
        assert all(
            cipher(app.state.settings).decrypt(entry.encrypted_vector)
            == unit(0).astype("<f4").tobytes()
            for entry in templates
        )
    before = snapshot(app)
    second = {**person_payload, "institutional_id": "STU-2"}
    response = register(
        client, second, manual=False, consent=AUTHORIZATION, files=enrollment_files()
    )
    assert response.status_code == 409
    assert snapshot(app) == before
    with app.state.sessions() as db:
        app.state.vision.refresh(db)
    assert set(app.state.vision.index.labels) == {person_id}


@pytest.mark.parametrize(
    "case",
    ["missing_guardian", "invalid_image", "repeated_image", "missing_consent", "mixed_methods"],
)
def test_registration_failure_rolls_back_all_related_data(client, app, person_payload, case):
    mock_vision(app)
    before = snapshot(app)
    person = {**person_payload, "age": 15 if case == "missing_guardian" else 25}
    files = enrollment_files()
    if case == "invalid_image":
        files[1] = ("files", ("invalid.jpg", b"not a jpeg", "image/jpeg"))
    elif case == "repeated_image":
        files = [files[0]] * 3
    response = register(
        client,
        person,
        manual=case == "mixed_methods",
        consent=None if case == "missing_consent" else AUTHORIZATION,
        files=files,
    )
    assert response.status_code == 422, response.text
    assert snapshot(app) == before
    with app.state.sessions() as db:
        assert db.get(Policy, 1).index_version == 0


def test_directories_reports_exports_and_schedules_are_scoped(
    client, person, attendance_session, session_payload
):
    staff = client.post(
        "/people",
        json={
            "full_name": "Office Employee",
            "institutional_id": "EMP-1",
            "category": "staff",
            "joined_on": "2026-01-01",
        },
    ).json()
    staff_session = client.post(
        "/sessions",
        json={
            **session_payload,
            "name": "Office shift",
            "category": "staff",
            "person_ids": [staff["id"]],
        },
    ).json()
    record_arrival(client, attendance_session, person)
    record_arrival(client, staff_session, staff)
    for member, session in [(person, attendance_session), (staff, staff_session)]:
        category = member["category"]
        assert [
            p["id"] for p in client.get("/people", params={"category": category}).json()["items"]
        ] == [member["id"]]
        assert (
            client.get(f"/people/{member['id']}", params={"category": "teacher"}).status_code == 404
        )
        params = {**period(session), "category": category}
        rows = client.get("/attendance", params=params).json()
        assert {r["person_id"] for r in rows} == {member["id"]}
        csv = client.get("/reports/export", params={**params, "kind": "csv"}).text
        assert member["full_name"] in csv
        assert (staff if member == person else person)["full_name"] not in csv
        assert {s["id"] for s in client.get("/sessions", params={"category": category}).json()} == {
            session["id"]
        }
        assert (
            client.get(
                f"/sessions/{session['id']}/roster", params={"category": "teacher"}
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/leaves",
                json={
                    "person_id": member["id"],
                    "starts_on": "2026-01-01",
                    "ends_on": "2026-01-02",
                    "reason": "Approved personal leave",
                },
            ).status_code
            == 201
        )
        assert {
            row["person_id"] for row in client.get("/leaves", params={"category": category}).json()
        } == {member["id"]}
    assert (
        client.get(
            "/attendance",
            params={**period(attendance_session), "category": "student", "person_id": staff["id"]},
        ).json()
        == []
    )
    assert client.get("/people", params={"category": "invalid"}).status_code == 422
    response = client.request(
        "DELETE", "/attendance", params={**period(attendance_session), "category": "student"}
    )
    assert response.json()["deleted"] == 1
    assert {
        r["person_id"] for r in client.get("/attendance", params=period(staff_session)).json()
    } == {staff["id"]}


def test_recovery_lists_do_not_cross_category_or_person_scope(
    client, person, attendance_session, session_payload
):
    staff = client.post(
        "/people",
        json={
            "full_name": "Office Employee",
            "institutional_id": "EMP-RECOVERY",
            "category": "staff",
            "joined_on": "2026-01-01",
        },
    ).json()
    staff_session = client.post(
        "/sessions",
        json={**session_payload, "category": "staff", "person_ids": [staff["id"]]},
    ).json()
    for member, session in [(person, attendance_session), (staff, staff_session)]:
        record_arrival(client, session, member)
    params = period(attendance_session)
    mixed = client.delete("/attendance", params=params).json()
    assert mixed["deleted"] == 2
    assert [entry["id"] for entry in client.get("/attendance-deletions").json()] == [
        mixed["deletion_id"]
    ]
    for scope in [{"category": "student"}, {"category": "staff"}, {"person_id": person["id"]}]:
        assert client.get("/attendance-deletions", params=scope).json() == []
    assert client.post(f"/attendance-deletions/{mixed['deletion_id']}/restore").status_code == 200
    single = client.delete("/attendance", params={**params, "category": "student"}).json()
    for scope in [{"category": "student"}, {"person_id": person["id"]}]:
        assert [
            entry["id"] for entry in client.get("/attendance-deletions", params=scope).json()
        ] == [single["deletion_id"]]
    assert client.get("/attendance-deletions", params={"category": "staff"}).json() == []
    assert client.get("/attendance-deletions", params={"person_id": staff["id"]}).json() == []


def test_dashboard_deduplicates_people_and_does_not_invent_absences(
    client, person, attendance_session, session_payload
):
    second = client.post("/sessions", json={**session_payload, "name": "Second lesson"}).json()
    record_arrival(client, attendance_session, person)
    record_arrival(client, second, person)
    dashboard = client.get("/dashboard").json()
    assert dashboard["registered"] == dashboard["checked_in"] == dashboard["today"]["present"] == 1
    assert dashboard["today"]["absent"] == 0
    assert len(dashboard["recent"]) == 2
    assert len(dashboard["trend"]) == 30
    assert (
        client.post(
            "/attendance/correct",
            json={
                "session_id": second["id"],
                "person_id": person["id"],
                "status": "late",
                "check_in": second["starts_at"],
                "reason": "Verified late classification",
                "expected_version": 1,
            },
        ).status_code
        == 200
    )
    dashboard = client.get("/dashboard").json()
    assert dashboard["checked_in"] == dashboard["today"]["late"] == 1
    assert dashboard["today"]["present"] == 0
    teacher = client.get("/dashboard", params={"category": "teacher"}).json()
    assert teacher["registered"] == teacher["checked_in"] == 0
    assert teacher["recent"] == teacher["sessions"] == teacher["administrative_activity"] == []
    assert client.get(f"/people/{person['id']}/activity").json()


def test_institution_settings_apply_to_new_workflows_preserve_existing_sessions(
    client, app, attendance_session
):
    response = client.put(
        "/institution", json={"name": "Test Academy", "timezone": "America/New_York"}
    )
    assert response.status_code == 200
    for path in ("/settings", "/overview", "/dashboard"):
        data = client.get(path).json()
        assert data["institution"] == "Test Academy" and data["timezone"] == "America/New_York"
    app.state.vision.load = Mock()
    assert client.post("/station/start").status_code == 201
    assert client.get("/station").json()["session"]["timezone"] == "America/New_York"
    assert (
        next(s for s in client.get("/sessions").json() if s["id"] == attendance_session["id"])[
            "timezone"
        ]
        == attendance_session["timezone"]
    )
    assert (
        client.put("/institution", json={"name": "Test", "timezone": "Not/AZone"}).status_code
        == 422
    )
    assert client.get("/settings").json()["institution"] == "Test Academy"


def test_new_endpoints_respect_permissions(client, person_payload):
    client.post(
        "/users",
        json={"username": "readonly", "password": "readonly-test-password", "role": "viewer"},
    )
    login = client.post(
        "/auth/login", json={"username": "readonly", "password": "readonly-test-password"}
    ).json()
    client.headers["Authorization"] = "Bearer " + login["token"]
    assert register(client, person_payload).status_code == 403
    assert (
        client.put("/institution", json={"name": "Other office", "timezone": "UTC"}).status_code
        == 403
    )
    data = client.get("/dashboard").json()
    assert data["administrative_activity"] == []
