from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from sqlalchemy import delete, select

from backend.api.common import lookup, user_view
from backend.auth import audit, current_user, digest, hasher, login, require, verify_password
from backend.browser_sessions import cookie_name, dashboard_origins
from backend.db import get_db, utcnow
from backend.models import LoginSession, User
from backend.schemas import LoginInput, PasswordInput, UserInput

router = APIRouter()


@router.post("/auth/login")
def sign_in(data: LoginInput, request: Request, db=Depends(get_db)):
    token, user = login(
        db,
        data.username,
        data.password,
        request.client.host if request.client else "local",
        request.app.state.settings.session_hours,
    )
    return {"token": token, "user": user_view(user)}


@router.get("/auth/me")
def me(user=Depends(current_user)):
    return user_view(user)


@router.post("/auth/browser-session-ticket")
def browser_session_ticket(request: Request, user=Depends(current_user)):
    token = request.headers["authorization"].split(" ", 1)[1]
    return {"ticket": request.app.state.browser_sessions.issue(token)}


def check_browser_origin(request):
    if request.headers.get("origin") not in dashboard_origins(request.app.state.settings):
        raise HTTPException(403, "Open the attendance dashboard to manage your browser session")


@router.post("/auth/browser-session")
def save_browser_session(
    request: Request, response: Response, ticket: str = Form(max_length=100), db=Depends(get_db)
):
    check_browser_origin(request)
    token = request.app.state.browser_sessions.consume(ticket)
    session = db.get(LoginSession, digest(token)) if token else None
    now = utcnow()
    if not session or session.expires_at <= now:
        raise HTTPException(401, "Sign-in confirmation expired. Please sign in again.")
    user = db.get(User, session.user_id)
    if not user or not user.active:
        raise HTTPException(401, "Account disabled")
    response.set_cookie(
        cookie_name(request.app.state.settings),
        token,
        max_age=max(1, int((session.expires_at - now).total_seconds())),
        expires=session.expires_at,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
    )
    return {"saved": True}


@router.post("/auth/browser-session/clear")
def clear_browser_session(request: Request, response: Response):
    check_browser_origin(request)
    response.delete_cookie(
        cookie_name(request.app.state.settings),
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
    )
    return {"cleared": True}


@router.post("/auth/logout", status_code=204)
def logout(request: Request, user=Depends(current_user), db=Depends(get_db)):
    token = request.headers["authorization"].split(" ", 1)[1]
    db.execute(delete(LoginSession).where(LoginSession.token_hash == digest(token)))
    audit(db, user, "logout", "user", user.id)
    db.commit()


@router.post("/auth/password", status_code=204)
def change_password(data: PasswordInput, user=Depends(current_user), db=Depends(get_db)):
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    user.password_hash = hasher.hash(data.new_password)
    db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    audit(db, user, "password_changed", "user", user.id)
    db.commit()


@router.get("/users")
def users(user=Depends(require("users")), db=Depends(get_db)):
    return [user_view(u) for u in db.scalars(select(User).order_by(User.username))]


@router.post("/users", status_code=201)
def create_user(data: UserInput, user=Depends(require("users")), db=Depends(get_db)):
    new_user = User(
        username=data.username, password_hash=hasher.hash(data.password), role=data.role
    )
    db.add(new_user)
    db.flush()
    audit(db, user, "user_created", "user", new_user.id, after={"role": data.role})
    db.commit()
    return user_view(new_user)


@router.patch("/users/{user_id}")
def toggle_user(user_id: int, active: bool, user=Depends(require("users")), db=Depends(get_db)):
    target = lookup(db, User, user_id)
    if target.id == user.id:
        raise HTTPException(409, "You cannot disable your own account")
    target.active = active
    db.execute(delete(LoginSession).where(LoginSession.user_id == user_id))
    audit(db, user, "user_status_changed", "user", user_id, after={"active": active})
    db.commit()
    return user_view(target)
