import secrets
import threading
import time
from urllib.parse import urlsplit

from backend.auth import digest


def cookie_name(settings):
    return f"attendance_session_{urlsplit(settings.api_url).port or 8000}"


def dashboard_origins(settings):
    origin = settings.dashboard_url.rstrip("/")
    parsed = urlsplit(origin)
    origins = [origin]
    if parsed.hostname in {"localhost", "127.0.0.1"}:
        alias = "localhost" if parsed.hostname == "127.0.0.1" else "127.0.0.1"
        origins.append(f"{parsed.scheme}://{alias}:{parsed.port or 80}")
    return origins


class BrowserSessionTickets:
    """Single-use, short-lived exchange codes; bearer tokens stay out of browser scripts."""

    def __init__(self):
        self.pending = {}
        self.lock = threading.Lock()

    def issue(self, token):
        with self.lock:
            now = time.monotonic()
            self.pending = {key: value for key, value in self.pending.items() if value[1] > now}
            if len(self.pending) >= 4096:
                self.pending.pop(next(iter(self.pending)))
            ticket = secrets.token_urlsafe(32)
            self.pending[digest(ticket)] = (token, now + 60)
            return ticket

    def consume(self, ticket):
        with self.lock:
            entry = self.pending.pop(digest(ticket), None)
            return entry[0] if entry and entry[1] > time.monotonic() else None
