from datetime import timedelta

import pytest
from sqlalchemy import select

from backend.db import utcnow
from backend.models import AuditLog, LoginSession, Person


def test_authentication_and_logout(client):
    assert client.get("/auth/me").json()["role"] == "super_admin"
    assert client.post("/auth/logout").status_code == 204
    assert client.get("/people").status_code == 401


def test_expiration(client, app):
    with app.state.sessions() as db:
        for session in db.scalars(select(LoginSession)):
            session.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert client.get("/auth/me").status_code == 401


def test_rate_limit(client):
    for _ in range(5):
        response = client.post("/auth/login", json={"username": "unknown", "password": "incorrect"})
        assert response.status_code == 401
    assert (
        client.post(
            "/auth/login", json={"username": "unknown", "password": "incorrect"}
        ).status_code
        == 429
    )


@pytest.mark.parametrize("role", ["viewer", "teacher", "staff_operator"])
def test_restricted_roles_cannot_enroll_or_change_settings(client, person_payload, role):
    assert (
        client.post(
            "/users", json={"username": role, "password": "another-password-123", "role": role}
        ).status_code
        == 201
    )
    token = client.post(
        "/auth/login", json={"username": role, "password": "another-password-123"}
    ).json()["token"]
    headers = {"Authorization": "Bearer " + token}
    assert client.get("/people", headers=headers).status_code == 200
    assert client.post("/people", headers=headers, json=person_payload).status_code == 403
    assert client.put("/settings", headers=headers, json={}).status_code == 403
    assert client.get("/audit", headers=headers).status_code == 403
    if role != "staff_operator":
        assert (
            client.post("/vision/streams", headers=headers, json={"session_id": 1}).status_code
            == 403
        )


@pytest.mark.parametrize("category", ["student", "teacher", "staff", "other"])
def test_register_categories(client, person_payload, category):
    person_payload.update(category=category, institutional_id=category, details={})
    response = client.post("/people", json=person_payload)
    assert response.status_code == 201
    assert response.json()["category"] == category
    assert not response.json()["enrolled"]


def test_unique_ids_roll_back(client, person_payload, person, app):
    assert client.post("/people", json=person_payload).status_code == 409
    assert client.get("/people").json()["total"] == 1
    with app.state.sessions() as db:
        assert len(db.scalars(select(Person)).all()) == 1
        assert (
            len(db.scalars(select(AuditLog).where(AuditLog.action == "person_created")).all()) == 1
        )


def test_validation(client, person_payload):
    person_payload["email"] = "bad-address"
    assert client.post("/people", json=person_payload).status_code == 422
    person_payload.pop("email")
    person_payload["details"] = {"employee_id": "EMP-1"}
    assert client.post("/people", json=person_payload).status_code == 422
    person_payload["details"] = {"class_id": 999}
    assert client.post("/people", json=person_payload).status_code == 422


def test_guardian_and_consent_revocation(client, person_payload):
    person_payload["is_minor"] = True
    person = client.post("/people", json=person_payload).json()
    url = f"/people/{person['id']}/consent"
    data = {"basis": "explicit_consent", "statement": "Authorized collection for school attendance"}
    assert client.post(url, json=data).status_code == 422
    assert (
        client.post(url, json={**data, "guardian": "Guardian authorization ref 12"}).status_code
        == 201
    )
    assert (
        client.request(
            "DELETE",
            f"/people/{person['id']}/biometrics",
            json={"reason": "Authorization withdrawn"},
        ).status_code
        == 204
    )
    assert client.get(f"/people/{person['id']}/enrollments").json()["consents"][0]["revoked_at"]


def test_delete_active_person_directly_and_preserve_audit(client, person):
    path = f"/people/{person['id']}"
    assert (
        client.request("DELETE", path, json={"reason": "Remove authorized profile"}).status_code
        == 204
    )
    assert client.get(path).status_code == 404
    assert any(x["action"] == "person_deleted" for x in client.get("/audit").json())


@pytest.mark.parametrize("role", ["admin", "teacher", "staff_operator", "viewer"])
def test_delete_person_requires_privacy_permission(client, person, role):
    client.post("/users", json={"username": role, "password": "role-test-password", "role": role})
    token = client.post(
        "/auth/login", json={"username": role, "password": "role-test-password"}
    ).json()["token"]
    assert (
        client.request(
            "DELETE",
            f"/people/{person['id']}",
            json={"reason": "Deleted from People"},
            headers={"Authorization": "Bearer " + token},
        ).status_code
        == 403
    )
    assert client.get(f"/people/{person['id']}").json()["active"]


def test_password_change_invalidates_sessions(client):
    response = client.post(
        "/auth/password",
        json={"current_password": "test-password-123", "new_password": "replacement-password-123"},
    )
    assert response.status_code == 204
    assert client.get("/auth/me").status_code == 401
    assert (
        client.post(
            "/auth/login",
            json={"username": "administrator", "password": "replacement-password-123"},
        ).status_code
        == 200
    )


def test_validation_response_does_not_disclose_password(client):
    password = "short-test"
    response = client.post(
        "/users", json={"username": "test_admin", "password": password, "role": "admin"}
    )
    assert response.status_code == 422
    assert password not in response.text
    assert "at least 12 characters" in response.text
    assert "input" not in response.json()["detail"][0]


def test_password_whitespace_is_preserved_through_login_and_change(client):
    password = "  exact password  "
    assert (
        client.post(
            "/users", json={"username": "space_user", "password": password, "role": "viewer"}
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/auth/login", json={"username": "space_user", "password": password.strip()}
        ).status_code
        == 401
    )
    login = client.post("/auth/login", json={"username": "space_user", "password": password})
    assert login.status_code == 200
    new_password = "  changed password  "
    assert (
        client.post(
            "/auth/password",
            headers={"Authorization": "Bearer " + login.json()["token"]},
            json={"current_password": password, "new_password": new_password},
        ).status_code
        == 204
    )
    assert (
        client.post(
            "/auth/login", json={"username": "space_user", "password": new_password}
        ).status_code
        == 200
    )


def test_successful_sign_ins_do_not_trigger_lockout(client):
    for _ in range(6):
        response = client.post(
            "/auth/login", json={"username": "administrator", "password": "test-password-123"}
        )
        assert response.status_code == 200
        assert (
            client.post(
                "/auth/logout",
                headers={
                    "Authorization": "Bearer " + response.json()["token"],
                },
            ).status_code
            == 204
        )
