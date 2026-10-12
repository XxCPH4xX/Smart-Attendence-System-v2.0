from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import numpy as np
import pytest
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import select

from backend.biometrics import cipher, decode_image
from backend.models import FaceTemplate, Person, Policy, User
from backend.people import bump_index
from vision.alignment import align_face, clamp_box, quality
from vision.camera import RemoteProcessor, draw_overlays
from vision.recognition import RecognitionIndex, normalize
from vision.tracking import StabilityTracker


def unit(index):
    vector = np.zeros(512, np.float32)
    vector[index] = 1
    return vector


def jpeg(color):
    stream = BytesIO()
    Image.new("RGB", (160, 160), color=color).save(stream, format="JPEG")
    return stream.getvalue()


def test_normalization_and_invalid_vectors():
    assert np.linalg.norm(normalize(np.ones(512))) == pytest.approx(1)
    for vector in [np.zeros(512), np.ones(128), np.full(512, np.nan)]:
        with pytest.raises(ValueError):
            normalize(vector)


@pytest.mark.parametrize("method", ["cosine", "knn", "ann"])
def test_known_unknown_and_ambiguous(method):
    index = RecognitionIndex([unit(0), unit(0), unit(1), unit(1)], [1, 1, 2, 2], method=method)
    assert index.match(unit(0)).person_id == 1
    assert index.match(unit(10)).status == "unknown"
    assert index.match(normalize(unit(0) + unit(1)), threshold=0.6).status == "ambiguous"
    assert RecognitionIndex([], []).match(unit(0)).person_id is None


def test_margin_compares_people_not_samples():
    index = RecognitionIndex([unit(0), unit(0)], [1, 1])
    assert index.match(unit(0)).person_id == 1


def test_actual_ann_query():
    index = RecognitionIndex(np.eye(512, dtype=np.float32)[:12], list(range(12)), method="ann")
    assert index.ann is not None
    assert index.match(unit(3)).person_id == 3


def test_temporal_stability_and_identity_switch():
    tracker = StabilityTracker(3, 1)
    face = ((0, 0, 100, 100), 1)
    assert tracker.update([face], 0) == [False]
    assert tracker.update([face], 0.5) == [False]
    assert tracker.update([face], 1) == [True]
    assert tracker.update([(face[0], 2)], 1.5) == [False]
    tracker.update([], 2)
    assert tracker.update([face], 2.5) == [False]
    assert tracker.update([face], 9) == [False]


def test_multiple_faces_track_independently():
    tracker = StabilityTracker(3, 1)
    faces = [((0, 0, 100, 100), 1), ((200, 0, 300, 100), 2)]
    tracker.update(faces, 0)
    tracker.update(list(reversed(faces)), 0.5)
    assert tracker.update(faces, 1) == [True, True]
    assert tracker.update([(faces[0][0], None), faces[1]], 1.5) == [False, True]


def test_alignment_geometry_and_quality():
    image = np.random.default_rng(1).integers(0, 255, (300, 500, 3), dtype=np.uint8)
    box = (200, 50, 380, 250)
    crop = align_face(image, [[240, 110], [340, 110], [290, 160]], box)
    assert crop.shape == (160, 160, 3)
    assert clamp_box((-20, 5, 600, 900), 500, 300) == (0, 5, 500, 300)
    with pytest.raises(ValueError):
        align_face(image, [[40, 110], [140, 110], [90, 160]], box)
    assert not quality(np.zeros((160, 160, 3), np.uint8), 100)[0]
    assert not quality(crop, 30)[0]


def test_invalid_image_rejected():
    with pytest.raises(HTTPException):
        decode_image(b"not an image")
    with pytest.raises(HTTPException):
        decode_image(jpeg("white"), maximum=10)


def test_camera_disconnect_and_overlay_bounds():
    processor = RemoteProcessor("http://localhost", "token", "stream")
    processor.client.close()
    processor.client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(httpx.ConnectError("offline"))
        ),
        base_url="http://localhost",
    )
    frame = np.zeros((120, 160, 3), np.uint8)
    assert processor.infer(frame)["error"] == "Recognition service unavailable"
    assert (
        draw_overlays(frame, [{"box": [0, 0, 30, 30], "name": "Test", "label": "Student"}]).shape
        == frame.shape
    )
    processor.close()
    processor.close()


def test_enrollment_encrypted_refresh_and_revoke(app, client, person, monkeypatch):
    consent = client.post(
        f"/people/{person['id']}/consent",
        json={"basis": "explicit_consent", "statement": "Consent to attendance face enrollment"},
    ).json()
    vision = app.state.vision
    vision.load = Mock()
    vision.detector = SimpleNamespace(
        detect=lambda *args: [
            SimpleNamespace(quality_ok=True, crop=np.zeros((160, 160, 3), np.uint8))
        ],
        close=lambda: None,
    )
    vision.embedder = SimpleNamespace(extract=lambda crops: np.stack([unit(0)] * len(crops)))
    files = [("files", (f"{c}.jpg", jpeg(c), "image/jpeg")) for c in ["red", "green", "blue"]]
    response = client.post(
        f"/people/{person['id']}/enroll", params={"consent_id": consent["id"]}, files=files
    )
    assert response.status_code == 200, response.text
    assert vision.index.match(unit(0)).person_id == person["id"]
    with app.state.sessions() as db:
        templates = db.scalars(select(FaceTemplate)).all()
        assert len(templates) == 3
        assert templates[0].encrypted_vector != unit(0).tobytes()
        assert len(cipher(app.state.settings).decrypt(templates[0].encrypted_vector)) == 512 * 4
        assert "encrypted_vector" not in client.get(f"/people/{person['id']}").text
    # Re-enrollment replaces, rather than appends to, a person's current templates.
    assert (
        client.post(
            f"/people/{person['id']}/enroll", params={"consent_id": consent["id"]}, files=files
        ).status_code
        == 200
    )
    with app.state.sessions() as db:
        assert len(db.scalars(select(FaceTemplate)).all()) == 3
    # Template expiry invalidates the cached index even without a version update.
    with monkeypatch.context() as clock:
        clock.setattr("backend.biometrics.utcnow", lambda: datetime.now(UTC) + timedelta(days=366))
        with app.state.sessions() as db:
            service_version = vision.index.version
            vision.refresh(db)
            assert vision.index.version == service_version
            assert vision.index.match(unit(0)).person_id is None
    assert (
        client.request(
            "DELETE",
            f"/people/{person['id']}/biometrics",
            json={"reason": "Consent withdrawn by participant"},
        ).status_code
        == 204
    )
    with app.state.sessions() as db:
        vision.refresh(db)
        assert vision.index.match(unit(0)).person_id is None


def test_raw_embeddings_cannot_be_submitted_as_attendance(client):
    assert (
        client.post("/attendance/recognize", json={"person_id": 1, "score": 1.0}).status_code == 404
    )
    assert (
        client.post("/vision/streams", json={"session_id": 1, "verified": True}).status_code == 422
    )


def test_stream_requires_real_stable_observations(
    app, client, person, attendance_session, monkeypatch
):
    service = app.state.vision
    service.load = Mock()
    service.analyze = Mock(
        return_value=[
            {"box": [0, 0, 100, 100], "person_id": person["id"], "name": "Test", "label": "Student"}
        ]
    )
    key = client.post("/vision/streams", json={"session_id": attendance_session["id"]}).json()[
        "stream_id"
    ]
    clock = [1000.0]
    monkeypatch.setattr("backend.biometrics.time.monotonic", lambda: clock[0])
    service.streams[key]["last_seen"] = clock[0]
    for offset, expected in [(0, False), (0.6, False), (1.2, True)]:
        clock[0] = 1000 + offset
        with app.state.sessions() as db:
            result = service.process_frame(
                db, db.get(User, 1), key, np.zeros((160, 160, 3), np.uint8)
            )
            assert result["faces"][0]["stable"] == expected
    assert result["faces"][0]["attendance_status"] == "pending_verification"


def test_inactive_index_exclusion(app, client, person):
    service = app.state.vision
    with app.state.sessions() as db:
        db.get(Person, person["id"]).active = False
        bump_index(db)
        db.commit()
        service.refresh(db)
        assert service.index.version == db.get(Policy, 1).index_version
        assert len(service.index.labels) == 0
