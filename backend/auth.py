import hashlib
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import delete, func, select

from backend.db import get_db, utcnow
from backend.models import AuditLog, LoginAttempt, LoginSession, User

hasher = PasswordHasher()
bearer = HTTPBearer(auto_error=False)
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(32))
PERMISSIONS = {
    "super_admin": {
        "read",
        "people",
        "enroll",
        "camera",
        "correct",
        "schedule",
        "settings",
        "users",
        "audit",
        "export",
        "privacy",
    },
    "admin": {"read", "people", "enroll", "camera", "correct", "schedule", "audit", "export"},
    "teacher": {"read", "export"},
    "staff_operator": {"read", "camera", "correct"},
    "viewer": {"read"},
}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def verify_password(password, encoded):
    try:
        return hasher.verify(encoded, password)
    except VerificationError:
        return False


def audit(db, user, action, entity, entity_id, before=None, after=None, reason=""):
    db.add(
        AuditLog(
            actor_id=user.id if user else None,
            action=action,
            entity=entity,
            entity_id=str(entity_id),
            before=before,
            after=after,
            reason=reason,
        )
    )


def login(db, username, password, client, hours):
    now = utcnow()
    # Separate account and host buckets prevent rotating usernames from evading throttling.
    buckets = [digest("account:" + username), digest("host:" + client)]
    db.execute(delete(LoginAttempt).where(LoginAttempt.at < now - timedelta(minutes=15)))
    counts = [
        db.scalar(
            select(func.count())
            .select_from(LoginAttempt)
            .where(LoginAttempt.bucket == b, LoginAttempt.at >= now - timedelta(minutes=15))
        )
        for b in buckets
    ]
    if counts[0] >= 5 or counts[1] >= 30:
        raise HTTPException(429, "Too many login attempts. Try again in 15 minutes.")
    attempts = [LoginAttempt(bucket=bucket) for bucket in buckets]
    db.add_all(attempts)
    db.commit()
    user = db.scalar(select(User).where(User.username == username))
    valid = verify_password(password, user.password_hash if user else DUMMY_HASH)
    if not valid or not user or not user.active:
        raise HTTPException(401, "Invalid username or password")
    # Reserve a rate-limit slot during verification, but only retain failed attempts.
    db.execute(
        delete(LoginAttempt).where(LoginAttempt.id.in_([attempt.id for attempt in attempts]))
    )
    token = secrets.token_urlsafe(48)
    db.add(
        LoginSession(
            token_hash=digest(token), user_id=user.id, expires_at=now + timedelta(hours=hours)
        )
    )
    audit(db, user, "login", "user", user.id)
    db.commit()
    return token, user


def current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db=Depends(get_db),
):
    if not credentials:
        raise HTTPException(401, "Sign in required")
    session = db.get(LoginSession, digest(credentials.credentials))
    if not session or session.expires_at <= utcnow():
        raise HTTPException(401, "Session expired; sign in again")
    user = db.get(User, session.user_id)
    if not user or not user.active:
        raise HTTPException(401, "Account disabled")
    return user


def require(permission):
    def check(user=Depends(current_user)):
        if permission not in PERMISSIONS.get(user.role, set()):
            raise HTTPException(403, "This account cannot perform that action")
        return user

    return check
