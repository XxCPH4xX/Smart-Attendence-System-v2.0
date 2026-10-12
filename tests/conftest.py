from datetime import timedelta

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.auth import hasher
from backend.config import Settings
from backend.db import Base, make_engine, session_factory, utcnow
from backend.main import create_app
from backend.models import Policy, User
from backend.schemas import PolicyInput


@pytest.fixture
def app(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        biometric_key=Fernet.generate_key().decode(),
        asset_dir=tmp_path / "assets",
    )
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    with session_factory(engine)() as db:
        db.add(
            Policy(
                id=1, values=PolicyInput(working_days=list(range(7))).model_dump(), index_version=0
            )
        )
        db.add(
            User(
                username="administrator",
                password_hash=hasher.hash("test-password-123"),
                role="super_admin",
            )
        )
        db.commit()
    return create_app(settings, engine)


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        response = client.post(
            "/auth/login", json={"username": "administrator", "password": "test-password-123"}
        )
        assert response.status_code == 200
        client.headers["Authorization"] = "Bearer " + response.json()["token"]
        yield client


@pytest.fixture
def person_payload():
    return {
        "institutional_id": "STU-1",
        "full_name": "Test Student",
        "category": "student",
        "joined_on": "2026-01-01",
        "details": {"class_id": None, "student_id": "STU-1"},
    }


@pytest.fixture
def person(client, person_payload):
    response = client.post("/people", json=person_payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def session_payload(person):
    now = utcnow()
    return {
        "name": "Test attendance",
        "category": "student",
        "timezone": "Asia/Dhaka",
        "starts_at": (now - timedelta(minutes=2)).isoformat(),
        "ends_at": (now + timedelta(hours=1)).isoformat(),
        "cutoff_at": (now + timedelta(minutes=30)).isoformat(),
        "person_ids": [person["id"]],
    }


@pytest.fixture
def attendance_session(client, session_payload):
    response = client.post("/sessions", json=session_payload)
    assert response.status_code == 201, response.text
    return response.json()
