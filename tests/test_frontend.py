from pathlib import Path

from streamlit.testing.v1 import AppTest

from frontend.client import APIError


def test_dashboard_pages_use_live_api_data(client, person, attendance_session, monkeypatch):
    import frontend.client as api
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

    for module in [api, administration, analytics, home, live, people, schedules]:
        monkeypatch.setattr(module, "request", request)
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
    pages = app.sidebar.radio[0].options
    assert pages == ["Home", "People", "Take attendance", "Records", "Settings"]
    for page in pages:
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception, (page, app.exception)
        assert not app.error, (page, app.error)

    # Administrative tools remain accessible without cluttering the main navigation.
    tools = app.selectbox[0].options
    for tool in tools:
        app.selectbox[0].select(tool).run()
        assert not app.exception, (tool, app.exception)
        assert not app.error, (tool, app.error)

    app.sidebar.radio[0].set_value("Home").run()
    next(button for button in app.button if button.label == "Create test profile").click().run()
    assert not app.exception
    next(button for button in app.button if button.label == "Add my face").click().run()
    assert app.sidebar.radio[0].value == "People"
    assert app.radio[0].value == "Enroll a face"
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

    # A demo session uses its own explicit roster, even with another session open.
    app.session_state["quick_person_id"] = demo["id"]
    app.session_state["new_attendance_session"] = True
    app.sidebar.radio[0].set_value("Take attendance").run()
    assert app.multiselect[0].value == [demo["id"]]
    next(
        button for button in app.button if button.label == "Start attendance session"
    ).click().run()
    assert not app.exception
    assert not app.error
    assert not app.toggle[0].value
    assert any(button.label == "Start camera" for button in app.button)
    session_id = app.session_state["preferred_session_id"]
    assert client.get(f"/sessions/{session_id}/roster").json() == [demo["id"]]
    assert app.selectbox[0].value == session_id


def test_sign_in_form_renders():
    app = AppTest.from_file(str(Path("frontend/app.py").resolve()), default_timeout=20).run()
    assert not app.exception
    assert len(app.text_input) == 2
    assert app.text_input[1].label == "Password"
