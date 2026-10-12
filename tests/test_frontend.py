from pathlib import Path

from streamlit.testing.v1 import AppTest

from frontend.client import APIError


def test_dashboard_pages_use_live_api_data(client, person, attendance_session, monkeypatch):
    import frontend.client as api
    from frontend.views import administration, analytics, live, people, schedules

    def request(method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        if response.is_error:
            raise APIError(str(response.json().get("detail")))
        if response.status_code == 204:
            return None
        if "application/json" in response.headers.get("content-type", ""):
            return response.json()
        return response.content

    for module in [api, administration, analytics, live, people, schedules]:
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
    for page in pages:
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception, (page, app.exception)
        assert not app.error, (page, app.error)


def test_sign_in_form_renders():
    app = AppTest.from_file(str(Path("frontend/app.py").resolve()), default_timeout=20).run()
    assert not app.exception
    assert len(app.text_input) == 2
    assert app.text_input[1].label == "Password"
