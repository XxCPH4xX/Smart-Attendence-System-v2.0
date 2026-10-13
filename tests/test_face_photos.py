from io import BytesIO
from unittest.mock import Mock

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

from frontend import face_photos


def photo(color):
    content = BytesIO()
    Image.new("RGB", (64, 64), color).save(content, format="JPEG")
    return (f"{color}.jpg", content.getvalue())


@pytest.fixture
def editor(monkeypatch):
    captures = {}

    def camera_input(*args, key, **kwargs):
        return captures.get(key)

    monkeypatch.setattr(face_photos.st, "camera_input", camera_input)
    quality = Mock(return_value={"acceptable": True, "feedback": []})
    monkeypatch.setattr(face_photos, "request", quality)
    app = AppTest.from_string("from frontend.face_photos import photo_editor\nphoto_editor(1)")
    app.session_state["samples_1"] = [photo(color) for color in ["red", "green", "blue"]]
    app.run()
    assert not app.exception
    return app, captures, quality


def test_remove_one_photo_keeps_other_photos(editor):
    app, _, quality = editor
    app.button(key="remove_photo_1_1").click().run()
    assert not app.exception
    assert app.session_state["samples_1"] == [photo("red"), photo("blue")]
    quality.assert_not_called()
    assert len([button for button in app.button if button.label == "Remove"]) == 2


def test_retake_replaces_only_selected_photo_after_quality_check(editor):
    app, captures, quality = editor
    original = list(app.session_state["samples_1"])
    app.button(key="retake_photo_1_1").click().run()
    assert app.session_state["samples_1"] == original
    captures["enrollment_1:0:capture_1_1"] = BytesIO(photo("yellow")[1])
    app.run()
    next(button for button in app.button if button.label == "Use photo").click().run()
    assert not app.exception
    saved = app.session_state["samples_1"]
    assert len(saved) == 3
    assert saved[0] == original[0]
    assert saved[2] == original[2]
    assert saved[1][1] == photo("yellow")[1]
    assert "retake_1" not in app.session_state
    quality.assert_called_once()


def test_bad_replacement_and_cancel_leave_original_unchanged(editor):
    app, captures, quality = editor
    original = list(app.session_state["samples_1"])
    quality.return_value = {"acceptable": False, "feedback": ["Move into better light."]}
    app.button(key="retake_photo_1_0").click().run()
    captures["enrollment_1:0:capture_1_1"] = BytesIO(photo("yellow")[1])
    app.run()
    next(button for button in app.button if button.label == "Use photo").click().run()
    assert not app.exception
    assert app.warning[0].value == "Move into better light."
    assert app.session_state["samples_1"] == original
    next(button for button in app.button if button.label == "Cancel retake").click().run()
    assert not app.exception
    assert app.session_state["samples_1"] == original
    assert "retake_1" not in app.session_state
    assert not any(button.label == "Use photo" for button in app.button)


def test_discard_pending_capture_then_clear_selection(editor):
    app, captures, quality = editor
    original = list(app.session_state["samples_1"])
    captures["enrollment_1:0:capture_1_0"] = BytesIO(photo("yellow")[1])
    app.run()
    next(
        button for button in app.button if button.label == "Retake" and not button.key
    ).click().run()
    assert not app.exception
    assert app.session_state["samples_1"] == original
    assert not any(button.label == "Use photo" for button in app.button)
    quality.assert_not_called()
    next(button for button in app.button if button.label == "Clear selected photos").click().run()
    assert not app.exception
    assert app.session_state["samples_1"] == []
    assert not any(button.label == "Remove" for button in app.button)


def test_removing_before_retake_target_still_replaces_correct_photo(editor):
    app, captures, _ = editor
    app.button(key="retake_photo_1_2").click().run()
    app.button(key="remove_photo_1_0").click().run()
    captures["enrollment_1:0:capture_1_1"] = BytesIO(photo("yellow")[1])
    app.run()
    next(button for button in app.button if button.label == "Use photo").click().run()
    assert not app.exception
    assert [data for _, data in app.session_state["samples_1"]] == [
        photo("green")[1],
        photo("yellow")[1],
    ]


def test_uploaded_photos_are_deduplicated_and_limited(monkeypatch):
    existing = [photo("red")]
    uploads = [BytesIO(photo(color)[1]) for color in ["red", "blue", "blue"]]
    for index, upload in enumerate(uploads):
        upload.name = f"upload-{index}.jpg"
    state = {"samples_1": existing.copy(), "uploads": uploads}
    monkeypatch.setattr(face_photos.st, "session_state", state)
    face_photos.add_uploads(1, "uploads")
    assert [data for _, data in state["samples_1"]] == [photo("red")[1], photo("blue")[1]]
    state["samples_1"] = [photo((index, 100, 150)) for index in range(12)]
    before = state["samples_1"].copy()
    face_photos.add_uploads(1, "uploads")
    assert state["samples_1"] == before
    assert "up to 12" in state["photo_notice_1"]
