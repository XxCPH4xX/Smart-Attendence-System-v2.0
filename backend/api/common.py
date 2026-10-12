from fastapi import HTTPException

from backend.auth import (
    PERMISSIONS,
)


def lookup(db, model, key):
    value = db.get(model, key)
    if not value:
        raise HTTPException(404, "Record not found")
    return value


def user_view(user):
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "active": user.active,
        "permissions": sorted(PERMISSIONS[user.role]),
    }
