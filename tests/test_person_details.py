import pytest


@pytest.mark.parametrize("age,minor", [(0, True), (17, True), (18, False), (120, False)])
def test_age_controls_guardian_requirement(client, person_payload, age, minor):
    response = client.post("/people", json={**person_payload, "age": age, "is_minor": not minor})
    assert response.status_code == 201
    person = response.json()
    assert person["age"] == age
    assert person["is_minor"] == minor
    consent = {"basis": "explicit_consent", "statement": "Face enrollment authorized for this test"}
    response = client.post(f"/people/{person['id']}/consent", json=consent)
    assert response.status_code == (422 if minor else 201)
    if minor:
        assert (
            client.post(
                f"/people/{person['id']}/consent",
                json={**consent, "guardian": "Guardian authorization ref-1"},
            ).status_code
            == 201
        )


@pytest.mark.parametrize("age", [-1, 121, 17.5, "17", True])
def test_invalid_age_is_rejected(client, person_payload, age):
    assert client.post("/people", json={**person_payload, "age": age}).status_code == 422


def test_legacy_minor_without_age_still_needs_guardian(client, person_payload):
    person = client.post("/people", json={**person_payload, "is_minor": True}).json()
    assert person["age"] is None
    assert (
        client.post(
            f"/people/{person['id']}/consent",
            json={
                "basis": "explicit_consent",
                "statement": "Face enrollment authorized for this test",
            },
        ).status_code
        == 422
    )


def test_correcting_age_requires_guardian_authorized_reenrollment(
    app, client, person, person_payload
):
    from test_station import enroll_fixture

    enroll_fixture(app, person["id"])
    assert client.get("/station").json()["enrolled_people"] == 1
    response = client.put(f"/people/{person['id']}", json={**person_payload, "age": 17})
    assert response.status_code == 200
    assert response.json()["is_minor"]
    assert not response.json()["enrolled"]
    assert client.get("/station").json()["enrolled_people"] == 0


def test_custom_type_is_saved_reused_filtered_and_exported(client, person_payload):
    from test_attendance_deletions import period, record_arrival

    payload = {
        **person_payload,
        "category": "other",
        "custom_type": " Contractor ",
        "details": {},
        "age": 30,
    }
    response = client.post("/people", json=payload)
    assert response.status_code == 201, response.text
    person = response.json()
    assert person["person_type"] == person["custom_type"] == "Contractor"
    second = client.post(
        "/people", json={**payload, "institutional_id": "CONT-2", "custom_type": "contractor"}
    ).json()
    assert second["custom_type"] == "Contractor"
    assert client.get("/people/types").json() == [
        "Student",
        "Teacher",
        "Staff",
        "Other",
        "Contractor",
    ]
    assert client.get("/people", params={"person_type": "CONTRACTOR"}).json()["total"] == 2
    assert client.get("/people", params={"person_type": "Other"}).json()["total"] == 0
    from datetime import timedelta

    from backend.db import utcnow

    now = utcnow()
    session = client.post(
        "/sessions",
        json={
            "name": "Contractor shift",
            "category": "other",
            "person_ids": [person["id"]],
            "starts_at": (now - timedelta(minutes=1)).isoformat(),
            "cutoff_at": (now + timedelta(minutes=30)).isoformat(),
            "ends_at": (now + timedelta(hours=1)).isoformat(),
        },
    ).json()
    record_arrival(client, session, person)
    params = {**period(session), "person_type": "Contractor"}
    assert client.get("/attendance", params=params).json()[0]["person_type"] == "Contractor"
    assert client.get("/attendance", params={**params, "person_type": "Other"}).json() == []
    report = client.get("/reports/export", params={**params, "kind": "csv"})
    assert report.status_code == 200
    assert "person_type" in report.text and "Contractor" in report.text
    assert (
        client.delete("/attendance", params={**params, "person_type": "Other"}).json()["deleted"]
        == 0
    )
    assert client.delete("/attendance", params=params).json()["deleted"] == 1


@pytest.mark.parametrize(
    "category,label",
    [("student", "Visitor"), ("other", "Staff"), ("other", " "), ("other", "x" * 81)],
)
def test_invalid_custom_type_is_rejected(client, person_payload, category, label):
    assert (
        client.post(
            "/people",
            json={**person_payload, "category": category, "custom_type": label, "details": {}},
        ).status_code
        == 422
    )
