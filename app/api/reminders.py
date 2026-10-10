"""A user's own reminder preference. Sending is done by scripts/send_reminders.py."""

import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, StringConstraints

from app.auth.deps import get_db, get_settings, require_user
from app.config import Settings
from app.db import Database

router = APIRouter()

CurrentUser = Annotated[dict, Depends(require_user)]
Db = Annotated[Database, Depends(get_db)]
Config = Annotated[Settings, Depends(get_settings)]

TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DEFAULT = {"enabled": False, "send_at": "07:00", "frequency": "daily"}


class ReminderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    send_at: Annotated[str, StringConstraints(pattern=TIME.pattern)]
    frequency: Literal["daily", "weekdays"]
    email: Annotated[str, StringConstraints(strip_whitespace=True, max_length=254)] = ""


def _read(conn, user_id: int, settings: Settings) -> dict:
    row = conn.execute(
        "SELECT u.email, r.enabled, r.send_at, r.frequency FROM users u"
        " LEFT JOIN reminders r ON r.user_id = u.id WHERE u.id = ?",
        (user_id,),
    ).fetchone()
    return {
        "enabled": bool(row["enabled"]) if row["enabled"] is not None else DEFAULT["enabled"],
        "send_at": row["send_at"] or DEFAULT["send_at"],
        "frequency": row["frequency"] or DEFAULT["frequency"],
        "email": row["email"] or "",
        "timezone": settings.app_timezone,
    }


@router.get("/api/reminders")
def get_reminder(user: CurrentUser, db: Db, settings: Config) -> dict:
    with db.read() as conn:
        return _read(conn, user["id"], settings)


@router.put("/api/reminders")
def put_reminder(body: ReminderIn, user: CurrentUser, db: Db, settings: Config) -> dict:
    if body.email and not EMAIL.match(body.email):
        raise HTTPException(status_code=422, detail="that does not look like an email address")
    if body.enabled and not body.email:
        raise HTTPException(status_code=422, detail="an email address is needed for reminders")
    with db.write() as conn:
        conn.execute("UPDATE users SET email = ? WHERE id = ?", (body.email or None, user["id"]))
        conn.execute(
            "INSERT INTO reminders (user_id, enabled, send_at, frequency) VALUES (?, ?, ?, ?)"
            " ON CONFLICT (user_id) DO UPDATE SET enabled = excluded.enabled,"
            " send_at = excluded.send_at, frequency = excluded.frequency",
            (user["id"], int(body.enabled), body.send_at, body.frequency),
        )
        return _read(conn, user["id"], settings)
