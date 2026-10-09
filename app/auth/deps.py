"""FastAPI dependencies: database access and the two authorisation gates."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app.auth.sessions import COOKIE_NAME, lookup_session, should_touch, touch_session
from app.config import Settings
from app.db import Database


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def require_user(
    request: Request,
    db: Annotated[Database, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """401 unless the request carries a valid, unexpired session cookie."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="not authenticated")
    with db.read() as conn:
        row = lookup_session(conn, settings, token)
    if row is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    if should_touch(row):
        with db.write() as conn:
            touch_session(conn, row["token_hash"])
    return {"id": row["id"], "username": row["username"], "role": row["role"]}


def require_admin(user: Annotated[dict, Depends(require_user)]) -> dict:
    """403 for anyone who is not an admin. Hiding a button is not security; this is."""
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    return user
