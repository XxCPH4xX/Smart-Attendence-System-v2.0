from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from frontend.client import APIError


@pytest.fixture
def ui_api(client, monkeypatch):
    import frontend.client as api
    from frontend import attendance_actions, face_photos
    from frontend.views import administration, analytics, home, live, people, schedules

    def request(method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        if response.is_error:
            raise APIError(str(response.json().get("detail")))
        if response.status_code == 204:
            return None
        if "application/json" in response.headers.get("content-type", ""):
            return response.json()
        return response.content

    for module in [
        api,
        attendance_actions,
        face_photos,
        administration,
        analytics,
        home,
        live,
        people,
        schedules,
    ]:
        monkeypatch.setattr(module, "request", request)
    return request


def test_dashboard_pages_use_live_api_data(client, person, attendance_session, monkeypatch, ui_api):
    from frontend.views import live

    client.post(
        "/attendance/correct",
        json={
            "session_id": attendance_session["id"],
            "person_id": person["id"],
            "status": "present",
            "check_in": attendance_session["starts_at"],
            "reason": "Verified manual check-in",
        },
    )
    app = AppTest.from_file(str(Path("frontend/app.py").resolve()), default_timeout=20)
    app.session_state["token"] = "test-session"
    app.run()
    assert not app.exception
    assert not app.error
    pages = [button.label for button in app.sidebar.button if (button.key or "").startswith("nav_")]
    assert pages == ["Home", "People", "Take attendance", "Records", "Settings"]
    for page in pages:
        next(button for button in app.sidebar.button if button.label == page).click().run()
        assert not app.exception, (page, app.exception)
        assert not app.error, (page, app.error)

    tools = app.selectbox[0].options
    for tool in tools:
        app.selectbox[0].select(tool).run()
        assert not app.exception, (tool, app.exception)
        assert not app.error, (tool, app.error)

    next(button for button in app.sidebar.button if button.label == "Home").click().run()
    next(button for button in app.button if button.label == "Create test profile").click().run()
    assert not app.exception
    next(button for button in app.button if button.label == "Add my face").click().run()
    assert app.session_state["page"] == "People"
    assert app.session_state["people_action"] == "Enroll a face"
    agree = next(button for button in app.button if button.label == "Agree and continue")
    assert not agree.disabled
    agree.click().run()
    assert app.error[0].value == "Confirm permission before continuing."
    next(box for box in app.checkbox if "informed permission" in box.label).check().run()
    next(button for button in app.button if button.label == "Agree and continue").click().run()
    assert not app.exception
    assert not app.error
    assert next(button for button in app.button if button.label == "Save face and finish").disabled
    demo = next(
        p for p in client.get("/people").json()["items"] if p["institutional_id"] == "DEMO-001"
    )
    assert not demo["enrolled"]
    assert len(client.get(f"/people/{demo['id']}/enrollments").json()["consents"]) == 1

    next(button for button in app.sidebar.button if button.label == "Take attendance").click().run()
    assert not app.exception
    assert not app.error
    assert len(app.multiselect) == 0
    assert any(button.label == "Start attendance station" for button in app.button)
    assert any(expander.label == "Customize this station" for expander in app.expander)

    client.app.state.vision.load = Mock()
    monkeypatch.setattr(
        live,
        "webrtc_streamer",
        lambda **kwargs: SimpleNamespace(
            video_processor=None, state=SimpleNamespace(playing=False)
        ),
    )
    next(
        button for button in app.button if button.label == "Start attendance station"
    ).click().run()
    assert not app.exception
    assert not app.error
    assert len(app.multiselect) == 0
    assert client.get("/station").json()["session"]["station"]
    next(button for button in app.button if button.label == "Stop attendance station").click().run()
    assert not app.exception
    assert "stream_id" not in app.session_state
    next(field for field in app.text_input if field.label == "Station name").set_value("Reception")
    next(button for button in app.button if button.label == "Save station settings").click().run()
    assert not app.exception
    assert not app.error
    assert client.get("/settings").json()["policy"]["station_name"] == "Reception"


def test_sign_in_form_renders():
    app = AppTest.from_file(str(Path("frontend/app.py").resolve()), default_timeout=20).run()
    assert not app.exception
    assert len(app.text_input) == 2
    assert app.text_input[1].label == "Password"


def test_records_delete_reset_undo_and_counters(
    client, person, attendance_session, session_payload, ui_api
):
    from test_attendance_deletions import period, record_arrival

    second = client.post("/sessions", json={**session_payload, "name": "Second class"}).json()
    for session in (attendance_session, second):
        record_arrival(client, session, person)
    ui = AppTest.from_file(str(Path("frontend/app.py").resolve()), default_timeout=20)
    ui.session_state["token"] = "test-session"
    ui.session_state["page"] = "Records"
    ui.run()
    buttons = [button for button in ui.button if button.label == "Delete record"]
    assert len(buttons) == 2
    buttons[0].click().run()
    assert not ui.exception and not ui.error
    assert len([button for button in ui.button if button.label == "Delete record"]) == 1
    next(button for button in ui.button if button.label == "Reset attendance").click().run()
    assert not ui.exception and not ui.error
    assert client.get("/attendance", params=period(attendance_session)).json() == []
    assert (
        next(metric for metric in ui.metric if metric.label == "Recorded attendance rate").value
        == "0.0%"
    )
    assert next(button for button in ui.button if button.label == "Reset attendance").disabled
    assert not any(button.label == "Delete record" for button in ui.button)
    next(
        button for button in ui.button if button.label == "Undo last attendance reset or deletion"
    ).click().run()
    assert not ui.exception and not ui.error
    assert (
        next(metric for metric in ui.metric if metric.label == "Recorded attendance rate").value
        == "100.0%"
    )
    next(button for button in ui.button if button.label == "Reset attendance").click().run()
    next(button for button in ui.sidebar.button if button.label == "Home").click().run()
    assert {metric.label: metric.value for metric in ui.metric} == {
        "People registered": "1",
        "Checked in": "0",
        "Waiting for review": "0",
    }


def test_live_reset_stops_camera_and_clears_today(client, person, app, ui_api):
    from test_attendance_deletions import record_arrival
    from test_station import enroll_fixture

    enroll_fixture(app, person["id"])
    app.state.vision.load = Mock()
    stream = client.post("/station/start").json()
    station = client.get("/station").json()["session"]
    record_arrival(client, station, person)
    ui = AppTest.from_file(str(Path("frontend/app.py").resolve()), default_timeout=20)
    ui.session_state["token"] = "test-session"
    ui.session_state["page"] = "Take attendance"
    ui.run()
    assert next(metric for metric in ui.metric if metric.label == "Checked in today").value == "1"
    next(button for button in ui.button if button.label == "Reset today's attendance").click().run()
    assert not ui.exception and not ui.error
    assert next(metric for metric in ui.metric if metric.label == "Checked in today").value == "0"
    assert next(metric for metric in ui.metric if metric.label == "Waiting for review").value == "0"
    assert stream["stream_id"] not in app.state.vision.streams
    assert client.get("/station").json()["enrolled_people"] == 1
    assert next(button for button in ui.button if button.label == "Start attendance station")


def test_custom_person_and_age_form(client, ui_api):
    ui = AppTest.from_file(str(Path("frontend/app.py").resolve()), default_timeout=20)
    ui.session_state["token"] = "test-session"
    ui.session_state["page"] = "People"
    ui.session_state["people_action"] = "Add person"
    ui.run()
    assert not any(box.label == "This person is under 18" for box in ui.checkbox)
    next(field for field in ui.selectbox if field.label == "Person type").set_value(
        "Custom type…"
    ).run()
    next(field for field in ui.text_input if field.label == "Custom person type").set_value(
        "Contractor"
    ).run()
    next(field for field in ui.text_input if field.label == "Full name").set_value(
        "Test Contractor"
    )
    next(field for field in ui.text_input if field.label == "Student or employee ID").set_value(
        "CONT-1"
    )
    next(field for field in ui.number_input if field.label == "Age (years)").set_value(25)
    next(button for button in ui.button if button.label == "Save and add face").click().run()
    assert not ui.exception and not ui.error
    saved = client.get("/people", params={"q": "CONT-1"}).json()["items"][0]
    assert saved["age"] == 25 and saved["person_type"] == "Contractor"
    assert not saved["is_minor"]


@pytest.mark.parametrize("role", ["super_admin", "admin", "teacher", "staff_operator", "viewer"])
def test_pages_render_for_each_role(client, ui_api, role):
    username = "ui_" + role
    assert (
        client.post(
            "/users",
            json={
                "username": username,
                "password": "ui-test-password-123",
                "role": role,
            },
        ).status_code
        == 201
    )
    login = client.post(
        "/auth/login",
        json={
            "username": username,
            "password": "ui-test-password-123",
        },
    ).json()
    client.headers["Authorization"] = "Bearer " + login["token"]
    ui = AppTest.from_file(str(Path("frontend/app.py").resolve()), default_timeout=20)
    ui.session_state["token"] = "test-session"
    ui.run()
    assert not ui.exception
    for page in [
        button.label for button in ui.sidebar.button if (button.key or "").startswith("nav_")
    ]:
        next(button for button in ui.sidebar.button if button.label == page).click().run()
        assert not ui.exception, (role, page, ui.exception)
        assert not ui.error, (role, page, ui.error)


def test_manual_station_attendance_uses_current_time(client, app, person, ui_api, monkeypatch):
    from zoneinfo import ZoneInfo

    from backend.db import utcnow
    from backend.models import User
    from backend.station import daily_station

    now = utcnow().replace(hour=7, minute=42, second=13, microsecond=0)
    with app.state.sessions() as db:
        station = daily_station(db, db.get(User, 1), "Asia/Dhaka", now=now)
    monkeypatch.setattr("frontend.views.schedules.utcnow", lambda: now)
    ui = AppTest.from_string(
        "from frontend.views.schedules import corrections\ncorrections()", default_timeout=20
    ).run()
    assert not ui.exception
    assert not ui.error
    check_in = next(field for field in ui.time_input if field.label == "Check-in time")
    assert check_in.value == now.astimezone(ZoneInfo("Asia/Dhaka")).time()
    ui.text_area[0].set_value("Verified arrival at the desk")
    next(button for button in ui.button if button.label == "Save attendance").click().run()
    assert not ui.exception
    assert not ui.error
    rows = client.get(
        "/attendance", params={"start": str(station.local_date), "end": str(station.local_date)}
    ).json()
    assert len(rows) == 1
    assert rows[0]["check_in"] == now.astimezone(ZoneInfo("Asia/Dhaka")).isoformat()


def test_scheduled_manual_checkin_preserves_start_seconds(
    client, person, attendance_session, ui_api
):
    ui = AppTest.from_string(
        "from frontend.views.schedules import corrections\ncorrections()", default_timeout=20
    ).run()
    ui.text_area[0].set_value("Arrival confirmed at scheduled start")
    next(button for button in ui.button if button.label == "Save attendance").click().run()
    assert not ui.exception
    assert not ui.error
    day = attendance_session["local_date"]
    rows = client.get("/attendance", params={"start": day, "end": day}).json()
    assert rows[0]["check_in"] == attendance_session["starts_at"]
    # Changing only the status must not round or silently shift the stored timestamp.
    next(field for field in ui.selectbox if field.label == "Attendance status").set_value(
        "late"
    ).run()
    ui.text_area[0].set_value("Corrected arrival classification")
    next(button for button in ui.button if button.label == "Save attendance").click().run()
    assert not ui.error
    updated = client.get("/attendance", params={"start": day, "end": day}).json()[0]
    assert updated["status"] == "late"
    assert updated["check_in"] == rows[0]["check_in"]


def test_delete_selected_person_in_one_click_and_restore_history(
    client, person, attendance_session, ui_api
):
    ui = AppTest.from_file(str(Path("frontend/app.py").resolve()), default_timeout=20)
    ui.session_state["token"] = "test-session"
    ui.session_state["page"] = "People"
    ui.run()
    assert not any(button.label == "Delete person" for button in ui.button)
    next(field for field in ui.selectbox if field.label == "Selected person").set_value(
        person["id"]
    ).run()
    next(button for button in ui.button if button.label == "Delete person").click().run()
    assert not ui.exception
    assert not ui.error
    assert not client.get(f"/people/{person['id']}").json()["active"]
    assert client.get(f"/sessions/{attendance_session['id']}/roster").json() == [person["id"]]
    next(field for field in ui.selectbox if field.label == "Show").set_value("Removed people").run()
    next(field for field in ui.selectbox if field.label == "Selected person").set_value(
        person["id"]
    ).run()
    next(button for button in ui.button if button.label == "Restore person").click().run()
    assert not ui.error
    assert client.get(f"/people/{person['id']}").json()["active"]


def test_records_link_and_delete_keep_attendance(client, person, attendance_session, ui_api):
    client.post(
        "/attendance/correct",
        json={
            "session_id": attendance_session["id"],
            "person_id": person["id"],
            "status": "present",
            "check_in": attendance_session["starts_at"],
            "reason": "Arrival confirmed in person",
        },
    )
    ui = AppTest.from_file(str(Path("frontend/app.py").resolve()), default_timeout=20)
    ui.session_state["token"] = "test-session"
    ui.session_state["page"] = "Records"
    ui.run()
    next(field for field in ui.selectbox if field.label == "Selected person").set_value(
        person["id"]
    ).run()
    next(button for button in ui.button if button.label == "Open person details").click().run()
    assert ui.session_state["page"] == "People"
    assert (
        next(field for field in ui.selectbox if field.label == "Selected person").value
        == person["id"]
    )
    next(button for button in ui.sidebar.button if button.label == "Records").click().run()
    next(field for field in ui.selectbox if field.label == "Selected person").set_value(
        person["id"]
    ).run()
    next(button for button in ui.button if button.label == "Delete person").click().run()
    assert not ui.exception
    assert not ui.error
    assert not client.get(f"/people/{person['id']}").json()["active"]
    day = attendance_session["local_date"]
    assert len(client.get("/attendance", params={"start": day, "end": day}).json()) == 1


@pytest.mark.parametrize(
    "page,section,field,reset",
    [
        ("People", "Add person", "Full name", "Reset form"),
        ("Settings", "Login accounts", "New username", "Reset account form"),
        ("Settings", "My account", "Current password", "Reset password form"),
        ("Settings", "Schedules & organization", "Session name", "Reset session form"),
        ("Settings", "Schedules & organization", "Leave reason", "Reset leave form"),
        ("Settings", "Schedules & organization", "Holiday name", "Reset holiday form"),
        ("Settings", "Schedules & organization", "Name", "Reset organization form"),
    ],
)
def test_reset_forms_keeps_saved_data(client, person, ui_api, page, section, field, reset):
    before_people = client.get("/people").json()
    before_accounts = client.get("/users").json()
    ui = AppTest.from_file(str(Path("frontend/app.py").resolve()), default_timeout=20)
    ui.session_state["token"] = "test-session"
    ui.session_state["page"] = page
    ui.run()
    if page == "People":
        next(button for button in ui.button if button.label == section).click().run()
    else:
        next(widget for widget in ui.selectbox if widget.label == "Manage").set_value(section).run()
    next(widget for widget in ui.text_input if widget.label == field).set_value("Unsaved entry")
    next(button for button in ui.button if button.label == reset).click().run()
    assert not ui.exception
    assert not ui.error
    assert next(widget for widget in ui.text_input if widget.label == field).value == ""
    assert ui.session_state["token"] == "test-session"
    assert client.get("/people").json() == before_people
    assert client.get("/users").json() == before_accounts
    for path in ["/sessions", "/leaves", "/holidays", "/catalog"]:
        assert client.get(path).json() == []


def test_reset_filters_and_station_settings(client, person, ui_api):
    ui = AppTest.from_file(str(Path("frontend/app.py").resolve()), default_timeout=20)
    ui.session_state["token"] = "test-session"
    ui.session_state["page"] = "People"
    ui.run()
    next(field for field in ui.text_input if field.label == "Find a person").set_value(
        "missing name"
    ).run()
    assert any(caption.value == "0 people found" for caption in ui.caption)
    next(button for button in ui.button if button.label == "Reset filters").click().run()
    assert next(field for field in ui.text_input if field.label == "Find a person").value == ""
    assert any(caption.value == "1 people found" for caption in ui.caption)
    next(button for button in ui.sidebar.button if button.label == "Records").click().run()
    next(field for field in ui.selectbox if field.label == "Show attendance for").set_value(
        "Custom dates"
    ).run()
    next(field for field in ui.selectbox if field.label == "Category").set_value("Staff").run()
    next(button for button in ui.button if button.label == "Clear filters").click().run()
    assert (
        next(field for field in ui.selectbox if field.label == "Show attendance for").value
        == "Today"
    )
    assert next(field for field in ui.selectbox if field.label == "Category").value == "All"
    next(button for button in ui.sidebar.button if button.label == "Take attendance").click().run()
    saved = client.get("/settings").json()["policy"]
    next(field for field in ui.text_input if field.label == "Station name").set_value(
        "Unsaved station name"
    )
    next(button for button in ui.button if button.label == "Reset unsaved settings").click().run()
    assert (
        next(field for field in ui.text_input if field.label == "Station name").value
        == saved["station_name"]
    )
    assert client.get("/settings").json()["policy"] == saved
    assert not ui.exception
    assert not ui.error
