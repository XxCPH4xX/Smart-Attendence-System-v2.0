from sqlalchemy import func, select

from backend.models import Consent, FaceTemplate, Person, User


def test_demo_is_idempotent_and_does_not_invent_consent_or_faces(client, app):
    first = client.post("/demo/person")
    second = client.post("/demo/person")
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["institutional_id"] == "DEMO-001"
    assert not first.json()["enrolled"]
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Person)) == 1
        assert db.scalar(select(func.count()).select_from(User)) == 1
        assert db.scalar(select(func.count()).select_from(Consent)) == 0
        assert db.scalar(select(func.count()).select_from(FaceTemplate)) == 0


def test_demo_does_not_overwrite_existing_person(client, person_payload):
    person_payload["institutional_id"] = "DEMO-001"
    existing = client.post("/people", json=person_payload).json()
    assert client.post("/demo/person").status_code == 409
    assert (
        client.get(f"/people/{existing['id']}").json()["full_name"] == person_payload["full_name"]
    )


def test_demo_requires_person_management_permission(client):
    client.post(
        "/users", json={"username": "viewer", "password": "viewer-test-password", "role": "viewer"}
    )
    token = client.post(
        "/auth/login", json={"username": "viewer", "password": "viewer-test-password"}
    ).json()["token"]
    assert (
        client.post("/demo/person", headers={"Authorization": "Bearer " + token}).status_code == 403
    )
