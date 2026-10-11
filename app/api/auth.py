"""Login, logout and /api/me. There is deliberately no registration route."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app import audit
from app.auth.deps import get_db, get_settings, require_user
from app.auth.sessions import COOKIE_NAME, create_session, delete_session
from app.config import Settings
from app.db import Database
from app.security import client_address

router = APIRouter()

INVALID_LOGIN = "invalid username or password"


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


def _cookie_args(settings: Settings) -> dict:
    return {"httponly": True, "samesite": "lax", "secure": settings.cookie_secure, "path": "/"}


@router.post("/api/login")
def login(
    body: LoginBody,
    request: Request,
    response: Response,
    db: Annotated[Database, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    passwords = request.app.state.passwords
    throttle = request.app.state.throttle
    address = client_address(request)

    wait = throttle.retry_after(body.username, address)
    if wait:
        audit.record(db, "login.throttled", request=request, actor_name=body.username)
        raise HTTPException(
            status_code=429, detail="too many attempts", headers={"Retry-After": str(wait)}
        )

    with db.read() as conn:
        user = conn.execute(
            "SELECT id, username, role, password_hash FROM users WHERE username = ? COLLATE NOCASE",
            (body.username,),
        ).fetchone()
    if user is None:
        ok = passwords.verify_unknown_user(body.password)
    else:
        ok = passwords.verify(user["password_hash"], body.password)
    if not ok:
        throttle.record_failure(body.username, address)
        audit.record(db, "login.failure", request=request, actor_name=body.username)
        raise HTTPException(status_code=401, detail=INVALID_LOGIN)

    throttle.record_success(body.username)
    with db.write() as conn:
        if passwords.needs_rehash(user["password_hash"]):
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (passwords.hash(body.password), user["id"]),
            )
        token = create_session(conn, settings, user["id"])
    audit.record(db, "login.success", request=request, actor=user)
    response.set_cookie(
        COOKIE_NAME, token, max_age=settings.session_max_age_seconds, **_cookie_args(settings)
    )
    return {"id": user["id"], "username": user["username"], "role": user["role"]}


@router.post("/api/logout", status_code=204)
def logout(
    request: Request,
    user: Annotated[dict, Depends(require_user)],
    db: Annotated[Database, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    with db.write() as conn:
        delete_session(conn, request.cookies[COOKIE_NAME])
    audit.record(db, "logout", request=request, actor=user)
    response = Response(status_code=204)
    response.delete_cookie(COOKIE_NAME, **_cookie_args(settings))
    return response


@router.get("/api/me")
def me(user: Annotated[dict, Depends(require_user)]) -> dict:
    return user
