from datetime import timedelta

import pytest
from sqlalchemy import select

from backend.browser_sessions import BrowserSessionTickets, cookie_name
from backend.db import utcnow
from backend.models import LoginSession

ORIGIN = {"Origin": "http://127.0.0.1:8501"}


def ticket(client):
    response = client.post("/auth/browser-session-ticket")
    assert response.status_code == 200
    return response.json()["ticket"]


def test_cookie_preserves_existing_session_expiry_and_is_not_api_authorization(client, app):
    code = ticket(client)
    response = client.post("/auth/browser-session", data={"ticket": code}, headers=ORIGIN)
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/" in cookie
    assert "Max-Age=" in cookie
    token = client.cookies[cookie_name(app.state.settings)]
    assert client.get("/auth/me", headers={"Authorization": "Bearer " + token}).status_code == 200
    assert (
        client.post("/auth/browser-session", data={"ticket": code}, headers=ORIGIN).status_code
        == 401
    )
    client.headers.pop("Authorization")
    assert client.get("/auth/me").status_code == 401
    assert client.post("/auth/browser-session-ticket").status_code == 401


@pytest.mark.parametrize(
    "origin", [None, "null", "https://untrusted.example", "http://localhost:9999"]
)
def test_session_cookie_rejects_untrusted_origins_without_consuming_ticket(client, origin):
    code = ticket(client)
    headers = {"Origin": origin} if origin else {}
    assert (
        client.post("/auth/browser-session", data={"ticket": code}, headers=headers).status_code
        == 403
    )
    assert client.post("/auth/browser-session/clear", headers=headers).status_code == 403
    assert (
        client.post("/auth/browser-session", data={"ticket": code}, headers=ORIGIN).status_code
        == 200
    )


def test_sign_out_revokes_cookie_token_and_clears_browser_cookie(client, app):
    code = ticket(client)
    client.post("/auth/browser-session", data={"ticket": code}, headers=ORIGIN)
    token = client.cookies[cookie_name(app.state.settings)]
    pending = ticket(client)
    assert client.post("/auth/logout").status_code == 204
    assert client.get("/auth/me", headers={"Authorization": "Bearer " + token}).status_code == 401
    assert (
        client.post("/auth/browser-session", data={"ticket": pending}, headers=ORIGIN).status_code
        == 401
    )
    response = client.post("/auth/browser-session/clear", headers=ORIGIN)
    assert response.status_code == 200
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert cookie_name(app.state.settings) not in client.cookies


def test_expired_sessions_cannot_be_saved_or_restored(client, app):
    code = ticket(client)
    with app.state.sessions() as db:
        for session in db.scalars(select(LoginSession)):
            session.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert (
        client.post("/auth/browser-session", data={"ticket": code}, headers=ORIGIN).status_code
        == 401
    )
    assert client.get("/auth/me").status_code == 401


def test_exchange_ticket_expires_after_one_minute(monkeypatch):
    tickets = BrowserSessionTickets()
    monkeypatch.setattr("backend.browser_sessions.time.monotonic", lambda: 100)
    code = tickets.issue("test-session-token")
    monkeypatch.setattr("backend.browser_sessions.time.monotonic", lambda: 161)
    assert tickets.consume(code) is None


def test_only_dashboard_origins_receive_credentialed_cors(client):
    for origin in ["http://127.0.0.1:8501", "http://localhost:8501"]:
        response = client.post(
            "/auth/browser-session", data={"ticket": ticket(client)}, headers={"Origin": origin}
        )
        assert response.headers["access-control-allow-origin"] == origin
        assert response.headers["access-control-allow-credentials"] == "true"
    response = client.post(
        "/auth/browser-session/clear", headers={"Origin": "https://untrusted.example"}
    )
    assert "access-control-allow-origin" not in response.headers
