from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from frontend.client import APIError


@pytest.fixture
def ui_api(client, monkeypatch):
    import frontend.client as api
    from frontend import attendance_actions, face_photos, registration
    from frontend.views import (
        administration,
        analytics,
        directory,
        enrollments,
        home,
        live,
        operations,
        people,
        schedules,
    )

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
        registration,
        directory,
        enrollments,
        operations,
        administration,
        analytics,
        home,
        live,
        people,
        schedules,
    ]:
        monkeypatch.setattr(module, "request", request)
    return request


def test_sign_in_form_renders():
    app = AppTest.from_file(str(Path("frontend/app.py").resolve()), default_timeout=20).run()
    assert not app.exception
    assert len(app.text_input) == 2
    assert app.text_input[1].label == "Password"


def test_refresh_restores_cookie_and_clear_session_does_not_restore_it_again(ui_api, monkeypatch):
    from streamlit.runtime.context import ContextProxy

    from backend.browser_sessions import cookie_name
    from backend.config import get_settings

    monkeypatch.setattr(
        ContextProxy,
        "cookies",
        property(lambda self: {cookie_name(get_settings()): "existing-browser-session"}),
    )
    ui = AppTest.from_file(str(Path("frontend/app.py").resolve()), default_timeout=20).run()
    assert not ui.exception and not ui.error
    assert ui.session_state["token"] == "existing-browser-session"
    assert any(button.label == "Overview" for button in ui.button)
    isolated = AppTest.from_string(
        "from frontend.browser_session import restore_session\n"
        "from frontend.client import clear_session\n"
        "restore_session()\nclear_session()\nrestore_session()"
    ).run()
    assert not isolated.exception
    assert "token" not in isolated.session_state


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


def workspace(page="Overview", section=None):
    ui = AppTest.from_file(str(Path("frontend/app.py").resolve()), default_timeout=20)
    ui.session_state["token"] = "test-session"
    ui.session_state["page"] = page
    if section:
        ui.session_state["section_" + page] = section
    return ui.run()


def click(ui, label):
    next(button for button in ui.button if button.label == label).click().run()
    assert not ui.exception, ui.exception
    assert not ui.error, ui.error


@pytest.mark.parametrize(
    "page",
    [
        "Students",
        "Teachers",
        "Staff",
        "Enrollment",
        "Attendance Operations",
        "Reports & Analytics",
        "Administration",
        "System Settings",
    ],
)
def test_all_workspace_sections_render(client, person, attendance_session, ui_api, page):
    ui = workspace(page)
    sections = [
        button.label
        for button in ui.button
        if (button.key or "").startswith("section_" + page + "_")
    ]
    assert sections
    for section in sections:
        click(ui, section)


def test_registration_draft_manual_custom_age_and_discard(client, ui_api):
    ui = workspace("Enrollment")
    click(ui, "Register other")
    for label, value in [
        ("Full name", "Test Contractor"),
        ("Institutional ID", "CONT-1"),
        ("Custom person type", "Contractor"),
    ]:
        next(field for field in ui.text_input if field.label == label).set_value(value)
    ui.number_input[0].set_value(25)
    click(ui, "Continue to institutional details")
    ui.run()
    assert client.get("/people").json()["total"] == 0
    click(ui, "Continue to face enrollment")
    ui.run()
    click(ui, "Manual attendance")
    click(ui, "Review registration")
    ui.run()
    assert client.get("/people").json()["total"] == 0
    click(ui, "Confirm registration")
    saved = client.get("/people").json()["items"][0]
    assert saved["age"] == 25 and saved["person_type"] == "Contractor"
    assert not saved["enrolled"] and not saved["is_minor"]
    click(ui, "New registration")
    click(ui, "Register student")
    click(ui, "Discard draft")
    assert client.get("/people").json()["total"] == 1


def test_directory_profile_actions_and_category_isolation(
    client, person, attendance_session, ui_api
):
    staff = client.post(
        "/people",
        json={
            "full_name": "Staff Only",
            "institutional_id": "STAFF-1",
            "category": "staff",
            "joined_on": "2026-01-01",
        },
    ).json()
    ui = workspace("Students")
    assert f"View profile_{person['id']}" in [b.key for b in ui.button]
    assert f"View profile_{staff['id']}" not in [b.key for b in ui.button]
    click(ui, "View profile")
    assert not any((b.key or "").startswith("section_Students_") for b in ui.button)
    for tab in [
        "Personal info",
        "Institution",
        "Attendance",
        "Face enrollment",
        "Activity",
        "Overview",
    ]:
        ui.button(key=f"profile_tab_{person['id']}_{tab}").click().run()
        assert not ui.exception and not ui.error
    click(ui, "Back to directory")
    click(ui, "View profile")
    click(ui, "Students")
    assert any(b.key == f"View profile_{person['id']}" for b in ui.button)
    click(ui, "Delete person")
    assert client.get(f"/people/{person['id']}").json()["active"]
    click(ui, "Cancel")
    assert client.get(f"/people/{person['id']}").json()["active"]
    click(ui, "Delete person")
    click(ui, "Confirm")
    assert not client.get(f"/people/{person['id']}").json()["active"]
    next(field for field in ui.selectbox if field.label == "Status").set_value(
        "Paused / removed"
    ).run()
    click(ui, "Restore check-ins")
    click(ui, "Confirm")
    assert client.get(f"/people/{person['id']}").json()["active"]
    assert client.get(f"/sessions/{attendance_session['id']}/roster").json() == [person["id"]]


def test_records_confirmation_delete_reset_undo_and_counters(
    client, person, attendance_session, session_payload, ui_api
):
    from test_attendance_deletions import period, record_arrival

    second = client.post("/sessions", json={**session_payload, "name": "Second class"}).json()
    for session in (attendance_session, second):
        record_arrival(client, session, person)
    ui = workspace("Reports & Analytics")
    click(ui, "Delete record")
    assert len(client.get("/attendance", params=period(attendance_session)).json()) == 2
    click(ui, "Confirm")
    assert len(client.get("/attendance", params=period(attendance_session)).json()) == 1
    click(ui, "Reset attendance")
    click(ui, "Confirm")
    assert client.get("/attendance", params=period(attendance_session)).json() == []
    assert next(m for m in ui.metric if m.label == "Recorded attendance rate").value == "0.0%"
    click(ui, "Undo last attendance reset or deletion")
    assert next(m for m in ui.metric if m.label == "Recorded attendance rate").value == "100.0%"
    click(ui, "Reset attendance")
    click(ui, "Confirm")
    click(ui, "Overview")
    metrics = {m.label: m.value for m in ui.metric}
    assert metrics["Total students"] == "1"
    assert metrics["Present today"] == metrics["Late today"] == metrics["Pending reviews"] == "0"


def test_live_reset_stops_camera_keeps_face_and_allows_restart(
    client, person, app, ui_api, monkeypatch
):
    from test_attendance_deletions import record_arrival
    from test_station import enroll_fixture

    from frontend.views import live

    enroll_fixture(app, person["id"])
    app.state.vision.load = Mock()
    stream = client.post("/station/start").json()
    record_arrival(client, client.get("/station").json()["session"], person)
    ui = workspace("Live Recognition")
    assert next(m for m in ui.metric if m.label == "Checked in today").value == "1"
    click(ui, "Reset today's attendance")
    click(ui, "Confirm")
    assert next(m for m in ui.metric if m.label == "Checked in today").value == "0"
    assert stream["stream_id"] not in app.state.vision.streams
    assert client.get("/station").json()["enrolled_people"] == 1
    monkeypatch.setattr(
        live,
        "webrtc_streamer",
        lambda **kwargs: SimpleNamespace(
            video_processor=None, state=SimpleNamespace(playing=False)
        ),
    )
    click(ui, "Start attendance station")
    click(ui, "Refresh camera")
    click(ui, "Stop attendance station")
    assert "stream_id" not in ui.session_state


def test_session_actions_confirm_reset_remove_and_restore(
    client, person, attendance_session, ui_api
):
    from test_attendance_deletions import period, record_arrival

    record_arrival(client, attendance_session, person)
    ui = workspace("Attendance Operations", "Active sessions")
    click(ui, "Remove session")
    click(ui, "Cancel")
    assert len(client.get("/sessions").json()) == 1
    click(ui, "Reset attendance")
    click(ui, "Confirm")
    assert client.get("/attendance", params=period(attendance_session)).json() == []
    click(ui, "Undo last attendance reset or deletion")
    assert len(client.get("/attendance", params=period(attendance_session)).json()) == 1
    click(ui, "Remove session")
    click(ui, "Confirm")
    assert client.get("/sessions").json() == []
    assert len(client.get("/attendance", params=period(attendance_session)).json()) == 1
    next(field for field in ui.checkbox if field.label == "Show removed sessions").set_value(
        True
    ).run()
    click(ui, "Restore session")
    assert len(client.get("/sessions").json()) == 1


@pytest.mark.parametrize(
    "page,section,field,reset",
    [
        ("Administration", "User accounts", "New username", "Reset account form"),
        ("Administration", "My account", "Current password", "Reset password form"),
        ("Attendance Operations", "Active sessions", "Session name", "Reset session form"),
        ("Attendance Operations", "Leave & holidays", "Leave reason", "Reset leave form"),
        ("Attendance Operations", "Leave & holidays", "Holiday name", "Reset holiday form"),
        ("Students", "Classes & sections", "Name", "Reset organization form"),
    ],
)
def test_reset_forms_preserves_saved_data(client, person, ui_api, page, section, field, reset):
    before = client.get("/people").json()
    ui = workspace(page, section)
    next(widget for widget in ui.text_input if widget.label == field).set_value("Unsaved entry")
    click(ui, reset)
    assert next(widget for widget in ui.text_input if widget.label == field).value == ""
    assert client.get("/people").json() == before
    for path in ["/sessions", "/leaves", "/holidays", "/catalog"]:
        assert client.get(path).json() == []


def test_clear_filters_and_dashboard_shortcuts(client, person, ui_api):
    ui = workspace("Students")
    ui.text_input[0].set_value("missing person").run()
    click(ui, "Clear filters")
    assert ui.text_input[0].value == ""
    assert any(b.label == "View profile" for b in ui.button)
    click(ui, "Overview")
    click(ui, "View absent today")
    assert next(s for s in ui.selectbox if s.label == "Attendance status").value == "absent"
    click(ui, "Clear filters")
    assert next(s for s in ui.selectbox if s.label == "Attendance status").value == "All"
    click(ui, "Overview")
    click(ui, "View present today")
    assert next(s for s in ui.selectbox if s.label == "Attendance status").value == "present"
    click(ui, "System Settings")
    saved = client.get("/settings").json()["policy"]
    next(s for s in ui.text_input if s.label == "Station name").set_value("Unsaved")
    click(ui, "Reset unsaved settings")
    assert (
        next(s for s in ui.text_input if s.label == "Station name").value == saved["station_name"]
    )
    assert client.get("/settings").json()["policy"] == saved
